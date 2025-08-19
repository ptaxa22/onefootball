import asyncio
import logging
import random
import sys
from datetime import datetime, timezone, timedelta
from itertools import cycle
from typing import List, Optional, Dict, Any, Tuple

from eth_account import Account
from pyuseragents import random as random_useragent
from eth_account.messages import encode_defunct
from loguru import logger
from curl_cffi.requests import AsyncSession, Response
from openpyxl.workbook import Workbook
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.text import Text
from rich.theme import Theme
import inquirer
from web3 import AsyncWeb3, AsyncHTTPProvider

from config import sleep, ref, max_concurrent_wallets, num_wallets, sleep_wallets

# Ваши GraphQL-запросы и пр.
from src.data import (
    query_verify,
    query_campaign,
    query_login,
    query_login_activities_panel,
    COMMON_HEADERS,
    query_user_me,
)
from src.logger import logging_setup
from src.task import (
    campaign_activities_panel_deil,
    verify_activity_deil,
    activity_quiz_detail,
    verify_activity_quiz,
)
from src.twitter import twitter
from src.utils import _make_request, create_signature, user_login

import warnings

warnings.filterwarnings("ignore", category=UserWarning, message="Curlm alread closed! quitting from process_data")

logger.add(sys.stdout, level="INFO")
logging_setup()
logging.getLogger('asyncio').setLevel(logging.CRITICAL)
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Загрузка данных ---

def _load_lines(file_path: str) -> List[str]:
    """Загружает и очищает строки из файла."""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        logger.error(f"Файл не найден: {file_path}")
        return []
    except Exception as e:
        logger.error(f"Ошибка загрузки файла {file_path}: {e}")
        return []

# Список приватных ключей
PRIVATE_KEYS = _load_lines("txt/private_keys.txt")
# Список прокси
PROXIES = _load_lines("txt/proxies.txt")
# Список Твиттер-токенов
TWITTER_TOKENS = _load_lines("txt/twitter_tokens.txt")

# Из приватных ключей создаём объекты Account
ACCOUNTS = [Account.from_key(key) for key in PRIVATE_KEYS]
PROXY_CYCLE = cycle(PROXIES) if PROXIES else None

PRIVY_HEADERS = {
    'accept': 'application/json',
    'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'cache-control': 'no-cache',
    'content-type': 'application/json',
    'dnt': '1',
    'origin': 'https://club.onefootball.com',
    'pragma': 'no-cache',
    'priority': 'u=1, i',
    'privy-app-id': 'clphlvsh3034xjw0fvs59mrdc',
    'privy-client': 'react-auth:2.4.1',
    'referer': 'https://club.onefootball.com/',
    'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'cross-site',
}

def _get_proxy_url(current_proxy: Optional[str] = None) -> Optional[str]:
    """Возвращает следующий прокси из цикла, пропуская текущий нерабочий."""
    if not PROXY_CYCLE:
        return None
    proxy = next(PROXY_CYCLE)
    while proxy == current_proxy and len(PROXIES) > 1:
        proxy = next(PROXY_CYCLE)
    return proxy

# --- API-запросы ---
async def siwe_accept_terms(session: AsyncSession, proxy: Optional[str], token: str) -> Dict[str, Any]:
    """Принимает условия использования."""
    headers = {
        **PRIVY_HEADERS,
        'authorization': f'Bearer {token}',
        'user-agent': random_useragent(),
    }
    return await _make_request(
        session,
        'https://auth.privy.io/api/v1/users/me/accept_terms',
        headers=headers,
        json_data={},
        proxy=proxy,
        operation_name='siwe_accept_terms'
    )

async def verify_activity(
        session: AsyncSession, proxy: Optional[str], token: str, privy_id_token: str, activityId='14f59386-4b62-4178-9cd0-cc3a8feb1773'
) -> Dict[str, Any]:
    """Верифицирует активность."""
    headers = {
        **COMMON_HEADERS,
        'authorization': f'Bearer {token}',
        'privy-id-token': privy_id_token,
        'x-apollo-operation-name': 'VerifyActivity',
    }
    json_data = {
        'operationName': 'VerifyActivity',
        'variables': {
            'data': {
                'activityId': activityId,
                'metadata': {
                    'referralCode': ref,
                },
            },
        },
        'query': query_verify,
    }
    return await _make_request(
        session,
        'https://api.deform.cc/',
        headers=headers,
        json_data=json_data,
        proxy=proxy,
        operation_name='verify_activity'
    )

async def campaign_activities(session: AsyncSession, proxy: Optional[str], token: str) -> Dict[str, Any]:
    """Получает данные об активностях кампании."""
    headers = {
        **COMMON_HEADERS,
        'authorization': f'Bearer {token}',
        'x-apollo-operation-name': 'CampaignActivities',
    }
    json_data = {
        'operationName': 'CampaignActivities',
        'variables': {
            'campaignId': '30ea55e5-cf99-4f21-a577-5c304b0c61e2',
        },
        'query': query_campaign,
    }
    return await _make_request(
        session,
        'https://api.deform.cc/',
        headers=headers,
        json_data=json_data,
        proxy=proxy,
        operation_name='campaign_activities'
    )

async def campaign_activities_panel(session: AsyncSession, proxy: Optional[str]) -> Optional[str]:
    """Получает ID кампании."""
    headers = {
        **COMMON_HEADERS,
        'cache-control': 'no-cache',
        'dnt': '1',
        'pragma': 'no-cache',
        'x-apollo-operation-name': 'CampaignSpotByCampaignIdAndReferralCode',
    }

    json_data = {
        'operationName': 'CampaignSpotByCampaignIdAndReferralCode',
        'variables': {
            'campaignId': '30ea55e5-cf99-4f21-a577-5c304b0c61e2',
            'referralCode': ref,
        },
        'query': query_login_activities_panel,
    }
    try:
        response: Response = await session.request(
            'POST',
            'https://api.deform.cc/',
            json=json_data,
            proxy=proxy,
            headers=headers
        )
        if response.status_code >= 400:
            logger.error(f"Error getting campaign ID - HTTP Error: {response.status_code}")
            if response.text:
                logger.error(f"Error getting campaign ID - HTTP Error Body: {await response.text()}")
            return None
        id = response.headers.get('x-amzn-RequestId')
        logger.debug(f"id: {id}")
        return id
    except Exception as e:
        logger.error(f"Error getting campaign ID: {e}")
        return None

async def user_me(session: AsyncSession, proxy: Optional[str], token: str, address: str) -> Optional[int]:
    """Получает количество очков пользователя."""
    headers = {
        **COMMON_HEADERS,
        'authorization': f'Bearer {token}',
        'x-apollo-operation-name': 'UserMe',
    }
    json_data = {
        'operationName': 'UserMe',
        'variables': {
            'campaignId': '30ea55e5-cf99-4f21-a577-5c304b0c61e2',
        },
        'query': query_user_me,
    }
    response = await _make_request(
        session,
        'https://api.deform.cc/',
        headers=headers,
        json_data=json_data,
        proxy=proxy,
        operation_name='user_me'
    )

    if (
            response
            and "data" in response
            and response["data"]["userMe"]
            and response["data"]["userMe"]['campaignSpot']
    ):
        points = response["data"]["userMe"]['campaignSpot']['points']
        logger.info(f"User points: {points} in {address}")
        return points
    else:
        logger.warning(f"Could not retrieve points for address {address}")
        return None

async def siwe_auth(
        account: Account,
        private_key: str,
        twitter_auth_token: Optional[str],
        full_guide: bool = True,
        wallet_number: int = 0,
        chek: bool = False
) -> Tuple[bool, Optional[int]]:
    if wallet_number // num_wallets != 0:
        logger.info(f'Sleeping for {sleep_wallets} seconds')
        await asyncio.sleep(sleep_wallets)
    """Выполняет авторизацию SIWE и связанные действия."""
    async with AsyncSession() as session:
        # 📌 1️⃣ Устанавливаем прокси с повторными попытками
        max_attempts = 3
        proxy = _get_proxy_url()
        for attempt in range(max_attempts):
            try:
                logger.info(f"Attempt {attempt+1}/{max_attempts} for wallet #{wallet_number}: {account.address} with {proxy or 'no proxy'}")

                # 📌 2️⃣ Получаем campaign_id
                campaign_id = await campaign_activities_panel(session, proxy)
                if not campaign_id:
                    raise Exception("Failed to get campaign_id")

                # 📌 3️⃣ Генерируем nonce для авторизации
                headers_init = {
                    **PRIVY_HEADERS,
                    'User-Agent': random_useragent(),
                    'privy-ca-id': campaign_id,
                }
                json_data_init = {'address': account.address}

                await asyncio.sleep(sleep)
                response_init = await _make_request(
                    session, 'https://auth.privy.io/api/v1/siwe/init',
                    headers=headers_init, json_data=json_data_init, proxy=proxy, operation_name='siwe_init'
                )

                if 'nonce' not in response_init:
                    raise Exception(f"SIWE init error: {response_init}")

                await asyncio.sleep(sleep)
                nonce = response_init['nonce']
                expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

                message = (
                    f"ofc.onefootball.com wants you to sign in with your Ethereum account:\n"
                    f"{account.address}\n\nBy signing, you are proving you own this wallet and logging in. "
                    f"This does not initiate a transaction or cost any fees.\n\n"
                    f"URI: https://ofc.onefootball.com\nVersion: 1\nChain ID: 1\nNonce: {nonce}\n"
                    f"Issued At: {expires_at}\nResources:\n- https://privy.io"
                )

                # 📌 4️⃣ Подписываем сообщение
                signature = await create_signature(message, private_key)

                json_data_auth = {
                    'message': message,
                    'signature': signature,
                    'chainId': 'eip155:1',
                    'walletClientType': 'okx_wallet',
                    'connectorType': 'injected',
                }

                await asyncio.sleep(sleep)
                response_auth = await _make_request(
                    session, 'https://auth.privy.io/api/v1/siwe/authenticate',
                    headers=headers_init, json_data=json_data_auth, proxy=proxy, operation_name='siwe_authenticate'
                )

                if not response_auth or 'token' not in response_auth or 'identity_token' not in response_auth:
                    raise Exception(f"SIWE auth error: {response_auth}")

                logger.info(f'Аккаунт {account.address} успешно авторизован!')
                token = response_auth['token']
                token_ref = response_auth['refresh_token']
                privy_id_token = response_auth['identity_token']

                # 📌 5️⃣ Принимаем условия и логинимся
                await asyncio.sleep(sleep)
                await siwe_accept_terms(session, proxy, token)

                await asyncio.sleep(sleep)
                user_token = await user_login(session, proxy, token)
                if not user_token:
                    raise Exception("User login failed")

                # 📌 6️⃣ Запускаем активности (кампании, рефералы)
                await asyncio.sleep(sleep)
                await campaign_activities(session, proxy, user_token)

                await asyncio.sleep(sleep)
                await verify_activity(session, proxy, user_token, privy_id_token)
                logger.info(f'Аккаунт {account.address} прошёл через реф - {ref}')

                # 📌 7️⃣ Работа с Twitter (если есть токен)
                if twitter_auth_token:
                    logger.info(f"Пытаемся подключить твитер {account.address}")
                    twitter_status = await twitter(session, proxy, token, twitter_auth_token, account.address, private_key)
                    if twitter_status != 0:
                        tasks = [
                            ('Твитер', '630499bc-8adb-411b-a503-d0da7de08e66'),
                            ('Подписка', '4590c2de-d1ac-43b4-a403-216255ec1e6e'),
                            ('Meet', '19ba588e-a6f7-4120-a8be-a29415e2ad4a'),
                            ('COSTA_4', 'ea4f75bd-21a8-4788-bf9d-c5a38f37150c'),
                            ('COSTA_5', 'd6083a1e-68e5-4c1d-91ce-009ef605b567'),
                            ('Iphone_16', '5b0902f1-75e7-4f7f-ada3-259b2f133dc6'),
                            ('Iphone_16', '568fb5f5-fbf5-4baa-805d-9fb076801389'),
                            ('Celebrate', '216a4d4c-9e64-480d-8bbb-4a1e0cedd10a'),
                            ('Spread', 'ab74de8e-4307-4e6c-969b-84c71113faf6'),
                            ('Tell', '31ad6a13-c354-413b-8980-d110ea9dffba'),
                            ('FIFA_1', '05abb049-2346-445d-8016-6fa7bc7bae9b'),
                            ('FIFA_2', '316bbba7-9acf-4ac9-953d-caa786e398ea'),
                            ('FIFA_3', '685ee31a-63e0-4063-86cd-e171bda52901'),
                            ('FIFA_4', 'e278f8ff-6fab-4883-aede-9a79c1f6edde'),
                            ('FIFA_5', '65ce608b-071a-4f4d-9e41-a9a82881abc1'),
                            ('TV_1', '6cefa7ce-e9bd-4cb8-a24f-88aad3559365'),
                            ('TV_2', '4aea2a6c-2fbb-47ef-a002-f07756f63b0d'),
                            ('SALE_1', '1fdf2efd-5691-4e45-88e0-1ae652f23dcf'),
                            ('SALE_2', '173eb8c1-602c-47ba-802a-09961a95e84f'),
                            ('Kickoff_1', 'baca9170-75e6-4daa-909d-5503f9dcbadd'),
                            ('Kickoff_2', 'f1eaeb3a-f535-470a-8742-04b9e477e9fc'),
                            ('500folow_1', 'c4b3adc9-2fda-44f3-b5d3-256e3e421505'),
                            ('500folow_2', '70bb6a80-5656-4f54-b50b-5f27874b1280'),
                            ('Space_1', '75affc24-fb64-4b24-87d4-a4237d257155'),
                            ('Space_2', 'b09b1368-4a66-4f49-9f68-08ffcadb9207'),
                            ('Mega_phone_1', 'ad3559b5-25aa-4d76-95df-6f6ed32d12ff'),
                            ('Mega_phone_2', 'f5d8798a-f482-494c-aba0-5e17fe27fc70'),
                            ('CoinList_1', '6221e4a9-5323-4c15-97aa-2e8527fd3569'),
                            ('CoinList_2', 'b09b1368-4a66-4f49-9f68-08ffcadb9207'),
                            ('CoinList_3', 'e3b06409-f6fd-494b-a233-fe01d0b4fb95'),
                            ('CoinList_4', '3b8cb839-b108-4b3a-b1cc-afb03812fd28'),
                            ('CoinList_5', '0b7cb19b-d373-4799-ace7-20bd54b6551e'),
                            ('CoinList_6', '69aab671-374b-444c-848d-fe99651dc519'),
                            ('Allowlist_1', '93ce3841-e1c9-4efb-afeb-d0bf67f33524'),
                            ('Allowlist_2', '7ba20a82-c236-4068-9872-7f5ac1db4603'),
                            ('Allowlist_3', '5c0b0ae6-0739-488c-9479-6b504a88dc13'),
                            ('OVERSUBSCRIBED_1', 'b5fa2297-ed6a-4f16-9d78-1654ed427bd2'),
                            ('OVERSUBSCRIBED_2', 'a1701cd8-cc9a-46c2-9c66-dbc351700ba5'),
                            ('presale_live_1', '5f0aa9fe-7c25-4b46-a83d-cf66e986b877'),
                            ('presale_live_2', '421855f3-408e-4567-b04d-8634e2c25dc7'),
                            ('presale_live_3', '0df42c86-7ef1-4a37-85d4-560ae3979f70'),
                            ('Animoca_1', '656c7402-3a6b-4410-9c67-83c59774245d'),
                            ('Animoca_2', '0f3c329e-9d33-4b91-b80f-9e29c2f40e79'),
                            ('IP_Launch_1', 'a4476b57-08e2-4af0-aaca-ef1fa270f2e0'),
                            ('IP_Launch_2', '9adfc34d-9901-4f3e-847d-cf8897af207a'),
                            ('IP_Launch_3', 'd94bef47-f43b-4747-9224-4bf37c51109e'),
                            ('Telegram', '9cfd0281-a3bb-4517-a6df-366c5f71ba2f'),
                            ('Nike_1', '645f2eb4-0efc-4400-8822-86fa07117191'),
                            ('Nike_2', 'faa4be2d-5bc7-4b98-96ce-08876d803934'),
                            ('Walrus_1', '4797b711-7e71-491f-8ae7-7fe1827856fa'),
                            ('Walrus_2', '70a2235a-c1ab-40c4-acbb-506fd08d698e'),
                        ]
                        max_attempts_tasks = 2
                        for task_name, task_id in tasks:
                            for task_attempt in range(max_attempts_tasks):
                                try:
                                    await asyncio.sleep(sleep)
                                    await campaign_activities(session, proxy, user_token)
                                    status = await verify_activity_deil(session, proxy, user_token, privy_id_token, task_id)
                                    logger.debug(f"Attempt {task_attempt+1}/{max_attempts_tasks} for {task_name}: {status}")
                                    if status == 'COMPLETED':
                                        logger.success(f'{task_name} выполнен успешно!')
                                        break
                                    elif status == 'ALREADY_COMPLETED':
                                        logger.warning(f'{task_name} уже выполнен.')
                                        break
                                    else:
                                        logger.error(f'Ошибка при выполнении {task_name}: {status}')
                                        if task_attempt == max_attempts_tasks - 1:
                                            logger.error(f"All attempts failed for {task_name}")
                                except Exception as e:
                                    logger.error(f"Attempt {task_attempt+1}/{max_attempts_tasks} for {task_name} failed: {e}")
                                    if task_attempt == max_attempts_tasks - 1:
                                        logger.error(f"All attempts failed for {task_name}")
                                    await asyncio.sleep(2)
                    else:
                        logger.warning(f"Twitter auth failed for {account.address}")
                else:
                    logger.warning(f"Нет Twitter-токена для {account.address}, пропускаем Twitter-задачу.")

                # 📌 8️⃣ Выполняем дополнительные активности (дейлики, квизы)
                if full_guide:
                    max_attempts_deil = 2
                    for deil_attempt in range(max_attempts_deil):
                        try:
                            await campaign_activities_panel_deil(session, proxy, user_token)
                            await asyncio.sleep(sleep)
                            status = await verify_activity_deil(session, proxy, user_token, privy_id_token)
                            logger.debug(f"Attempt {deil_attempt+1}/{max_attempts_deil} for Дейлик: {status}")
                            if status == 'COMPLETED':
                                logger.success(f'Дейлик выполнен успешно!')
                                break
                            elif status == 'ALREADY_COMPLETED':
                                logger.warning(f'Дейлик уже выполнен.')
                                break
                            else:
                                logger.error(f'Ошибка при выполнении Дейлика: {status}')
                                if deil_attempt == max_attempts_deil - 1:
                                    logger.error(f"All attempts failed for Дейлик")
                        except Exception as e:
                            logger.error(f"Attempt {deil_attempt+1}/{max_attempts_deil} for Дейлик failed: {e}")
                            if deil_attempt == max_attempts_deil - 1:
                                logger.error(f"All attempts failed for Дейлик")
                            await asyncio.sleep(2)

                    # Квизы
                    quiz_tasks = [
                        ('Квиз 1', 1),
                        ('Квиз 2', 2),
                        ('Квиз 3', 3),
                        ('Квиз 4', 4),
                        ('Квиз 5', 5),  
                        ('Квиз 6', 6),  
                    ]
                    max_attempts_quiz = 2
                    for quiz_name, num in quiz_tasks:
                        for quiz_attempt in range(max_attempts_quiz):
                            try:
                                await asyncio.sleep(sleep)
                                await activity_quiz_detail(session, proxy, user_token, num=num)
                                status = await verify_activity_quiz(session, proxy, user_token, privy_id_token, num=num)
                                logger.debug(f"Attempt {quiz_attempt+1}/{max_attempts_quiz} for {quiz_name}: {status}")
                                if status == 'COMPLETED':
                                    logger.success(f'{quiz_name} выполнен успешно!')
                                    break
                                elif status == 'ALREADY_COMPLETED':
                                    logger.warning(f'{quiz_name} уже выполнен.')
                                    break
                                else:
                                    logger.error(f'Ошибка при выполнении {quiz_name}: {status}')
                                    if quiz_attempt == max_attempts_quiz - 1:
                                        logger.error(f"All attempts failed for {quiz_name}")
                            except Exception as e:
                                logger.error(f"Attempt {quiz_attempt+1}/{max_attempts_quiz} for {quiz_name} failed: {e}")
                                if quiz_attempt == max_attempts_quiz - 1:
                                    logger.error(f"All attempts failed for {quiz_name}")
                                await asyncio.sleep(2)

                # 📌 9️⃣ Завершаем проверку дейликов
                if not full_guide and not chek:
                    max_attempts_deil = 2
                    for deil_attempt in range(max_attempts_deil):
                        try:
                            await campaign_activities_panel_deil(session, proxy, user_token)
                            await asyncio.sleep(sleep)
                            status = await verify_activity_deil(session, proxy, user_token, privy_id_token)
                            logger.debug(f"Attempt {deil_attempt+1}/{max_attempts_deil} for Дейлик: {status}")
                            if status == 'COMPLETED':
                                logger.success(f'Дейлик выполнен успешно!')
                                break
                            elif status == 'ALREADY_COMPLETED':
                                logger.warning(f'Дейлик уже выполнен.')
                                break
                            else:
                                logger.error(f'Ошибка при выполнении Дейлика: {status}')
                                if deil_attempt == max_attempts_deil - 1:
                                    logger.error(f"All attempts failed for Дейлик")
                        except Exception as e:
                            logger.error(f"Attempt {deil_attempt+1}/{max_attempts_deil} for Дейлик failed: {e}")
                            if deil_attempt == max_attempts_deil - 1:
                                logger.error(f"All attempts failed for Дейлик")
                            await asyncio.sleep(2)

                # 📌 🔟 Получаем очки и завершаем
                points = await user_me(session, proxy, user_token, account.address)
                logger.info(f"Initial points: {points}")
                await asyncio.sleep(10)  # Ждём синхронизации
                points = await user_me(session, proxy, user_token, account.address)
                logger.info(f"Points after delay: {points}")
                return True, points

            except Exception as e:
                logger.error(f"Attempt {attempt+1}/{max_attempts} failed: {e}")
                if attempt < max_attempts - 1:
                    proxy = _get_proxy_url(proxy)
                    await asyncio.sleep(2)
                else:
                    logger.error(f"All attempts failed for {account.address}")
                    return False, None

async def process_account(
        account: Account,
        private_key: str,
        twitter_auth_token: Optional[str],
        full_guide: bool,
        wallet_number: int,
        chek: bool,
) -> Tuple[str, str, Optional[int]]:
    """Обрабатывает один аккаунт и возвращает данные для отчета."""
    success, points = await siwe_auth(
        account,
        private_key,
        twitter_auth_token=twitter_auth_token,
        full_guide=full_guide,
        wallet_number=wallet_number,
        chek=chek
    )
    if success:
        logger.success(f"Account {account.address}: Success")
    else:
        logger.error(f"Account {account.address}: Error")
    return private_key, account.address, points

# --- Новая функция для обработки с семафором ---
semaphore = asyncio.Semaphore(max_concurrent_wallets)

async def process_account_with_semaphore(
        account: Account,
        private_key: str,
        i: int,
        full_guide: bool,
        chek: bool
) -> Tuple[str, str, Optional[int]]:
    async with semaphore:
        # Берём Twitter-токен, если он есть под таким индексом
        twitter_auth_token = TWITTER_TOKENS[i] if i < len(TWITTER_TOKENS) else None
        return await process_account(
            account,
            private_key,
            twitter_auth_token,
            full_guide,
            i + 1,
            chek,
        )

async def run_full_guide():
    """Запускает полную цепочку действий с ограничением параллелизма."""
    if not ACCOUNTS or not PRIVATE_KEYS:
        logger.error("Нет приватных ключей для обработки.")
        return

    if not PROXIES:
        logger.warning("Нет прокси, будет выполнятся без прокси.")

    tasks = [
        process_account_with_semaphore(
            account,
            private_key,
            i,
            full_guide=True,
            chek=False
        )
        for i, (account, private_key) in enumerate(zip(ACCOUNTS, PRIVATE_KEYS))
    ]
    await asyncio.gather(*tasks)

async def run_daily_only():
    """Запускает только дейлик с ограничением параллелизма."""
    if not ACCOUNTS or not PRIVATE_KEYS:
        logger.error("Нет приватных ключей для обработки.")
        return

    if not PROXIES:
        logger.warning("Нет прокси, будет выполнятся без прокси.")

    async with AsyncSession() as session:
        tasks = [
            process_account_with_semaphore(
                account,
                private_key,
                i,
                full_guide=False,
                chek=False
            )
            for i, (account, private_key) in enumerate(zip(ACCOUNTS, PRIVATE_KEYS))
        ]
        await asyncio.gather(*tasks)

async def run_chek():
    """Запускает чекер (получение поинтов) с ограничением параллелизма."""
    if not ACCOUNTS or not PRIVATE_KEYS:
        logger.error("Нет приватных ключей для обработки.")
        return

    if not PROXIES:
        logger.warning("Нет прокси, будет выполнятся без прокси.")

    async with AsyncSession() as session:
        tasks = [
            process_account_with_semaphore(
                account,
                private_key,
                i,
                full_guide=False,
                chek=True
            )
            for i, (account, private_key) in enumerate(zip(ACCOUNTS, PRIVATE_KEYS))
        ]
        results = await asyncio.gather(*tasks)

    wb = Workbook()
    ws = wb.active
    ws.append(["Private Key", "Address", "Points"])  # Заголовки
    for row in results:
        ws.append(row)

    wb.save("account_results.xlsx")
    logger.success("Результаты сохранены в account_results.xlsx")

def main_menu(console: Console) -> str:
    questions = [
        inquirer.List(
            'action',
            message="What do you want to do?",
            choices=['Run the Full Guide', 'Run Daily Tasks', 'Run Checker', 'Exit'],
            carousel=True
        ),
    ]
    answers = inquirer.prompt(questions)
    return answers['action']

async def main():
    """Главная функция для запуска программы."""
    console = Console(theme=Theme({
        "prompt": "bold cyan",
        "info": "bold green",
        "error": "bold red",
        "warning": "bold yellow",
        "success": "bold green",
        "title": "bold magenta",
        "description": "bold blue",
        "selected": "bold white on #666666",
        "unselected": "white"
    }))

    # Декоративная панель заголовка
    console.print(Panel(
        Text("OFC AUTO\nWelcome to the Onefootball Campaign Automation!", justify="center", style="title"),
        title="[bold cyan]Main Menu[/bold cyan]",
        subtitle="Automate your tasks with ease and style",
        border_style="bold magenta",
        padding=(1, 2)
    ))

    # Описание доступных действий
    console.print(Panel(
        Text(
            "[1] Run the Full Guide - Includes all steps of the campaign\n"
            "[2] Run Daily Tasks - Focus only on daily campaign updates\n"
            "[3] Run Checker - Check all account points\n"
            "[exit] Quit the program",
            style="description",
            justify="left"
        ),
        title="[bold cyan]Available Actions[/bold cyan]",
        border_style="bold blue",
        padding=(1, 2)
    ))

    selected_action = main_menu(console)

    if selected_action == "Run the Full Guide":
        console.print(Panel(
            Text("Starting Full Guide...", justify="center", style="info"),
            border_style="green",
            padding=(1, 2)
        ))
        with Progress(
                SpinnerColumn(style="info"),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                console=console
        ) as progress:
            task = progress.add_task("Running full guide...", total=100)
            for _ in range(100):
                await asyncio.sleep(0.05)
                progress.update(task, advance=1)
        await run_full_guide()
        console.print("[success]Full guide completed![/success]")

    elif selected_action == "Run Daily Tasks":
        console.print(Panel(
            Text("Starting Daily Tasks...", justify="center", style="info"),
            border_style="blue",
            padding=(1, 2)
        ))
        await run_daily_only()
        console.print("[success]Daily tasks completed![/success]")

    elif selected_action == "Run Checker":
        console.print(Panel(
            Text("Starting Checker...", justify="center", style="info"),
            border_style="blue",
            padding=(1, 2)
        ))
        await run_chek()
        console.print("[success]Checker completed![/success]")

    elif selected_action == "Exit":
        console.print(Panel(
            Text("Exiting the program. Goodbye!", justify="center", style="warning"),
            border_style="red",
            padding=(1, 2)
        ))

if __name__ == "__main__":
    asyncio.run(main())
