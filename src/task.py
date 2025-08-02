# task.py
from typing import Optional

from src.data import query_deil, query_verify_deil, query_quiz, query_quiz_verify, COMMON_HEADERS, json_data_qz_1, \
    json_data_qz_2, json_data_qz1, json_data_qz2, json_data_3, json_data_qz4, json_data_4, json_data_qz3, json_data_qz_5, json_data_qz_6, json_data_qz_7 
from src.utils import _make_request
from curl_cffi.requests import AsyncSession
from loguru import logger


async def campaign_activities_panel_deil(session: AsyncSession, proxy: Optional[str], token: str) -> None:
    """Получает данные для панели активностей кампании (дейлик)."""
    headers = {
        **COMMON_HEADERS,
        'authorization': f'Bearer {token}',
        'x-apollo-operation-name': 'CampaignActivitiesPanel',
    }

    json_data = {
        'operationName': 'CampaignActivitiesPanel',
        'variables': {
            'campaignId': '30ea55e5-cf99-4f21-a577-5c304b0c61e2',
            'isTrusted': True,
        },
        'query': query_deil,
    }

    await _make_request(
        session,
        'https://api.deform.cc/',
        headers=headers,
        json_data=json_data,
        proxy=proxy,
        operation_name='campaign_activities_panel_deil'
    )


async def verify_activity_deil(session: AsyncSession, proxy: Optional[str], token: str, token_id: str, activityId = 'c326c0bb-0f42-4ab7-8c5e-4a648259b807') -> str:
    """
    Верифицирует активность (дейлик).
    Возвращает статус выполнения:
    - 'COMPLETED' - дейлик выполнен успешно.
    - 'ALREADY_COMPLETED' - дейлик уже был выполнен ранее.
    - 'ERROR' - ошибка в запросе или неизвестный статус.
    """
    headers = {
        **COMMON_HEADERS,
        'authorization': f'Bearer {token}',
        'privy-id-token': token_id,
        'x-apollo-operation-name': 'VerifyActivity',
    }

    json_data = {
        'operationName': 'VerifyActivity',
        'variables': {
            'data': {
                'activityId': activityId,
            },
        },
        'query': query_verify_deil,
    }

    response_data = await _make_request(
        session,
        'https://api.deform.cc/',
        headers=headers,
        json_data=json_data,
        proxy=proxy,
        operation_name='verify_activity_deil'
    )

    # Проверка ответа
    if isinstance(response_data, dict):
        if 'errors' in response_data and response_data['errors']:
            return 'ALREADY_COMPLETED'
        if 'data' in response_data and 'verifyActivity' in response_data['data']:
            record = response_data['data']['verifyActivity'].get('record', {})
            status = record.get('status')
            if status == 'COMPLETED':
                return 'COMPLETED'

    logger.error("Не удалось проверить статус, неизвестный ответ API.")
    return 'ERROR'



async def activity_quiz_detail(session: AsyncSession, proxy: Optional[str], token: str, num=None) -> None:
    """Получает детали квиза."""
    headers = {
        **COMMON_HEADERS,
        'authorization': f'Bearer {token}',
        'x-apollo-operation-name': 'ActivityQuizDetail',
    }
    if num == 2:
        json_data = json_data_qz2
    elif num == 3:
        json_data = json_data_qz3
    elif num == 4:
        json_data = json_data_qz4
    elif num == 5:
        json_data = {
            'operationName': 'ActivityQuizDetail',
            'variables': {
                'activityId': '9f687bd8-12be-4ded-863d-7df31c736403'
            },
            'query': query_quiz
        }
    elif num == 6:
        json_data = {
            'operationName': 'ActivityQuizDetail',
            'variables': {
                'activityId': 'bc2ff6fa-1601-4335-ab96-02cfb4fb70e2'
            },
            'query': query_quiz
        }
    else:
        json_data = json_data_qz1

    await _make_request(
        session,
        'https://api.deform.cc/',
        headers=headers,
        json_data=json_data,
        proxy=proxy,
        operation_name='activity_quiz_detail'
    )


async def verify_activity_quiz(session: AsyncSession, proxy: Optional[str], token: str, token_id: str, num=None) -> str:
    """Верифицирует активность (квиз)."""
    if num == 2:
        json_data = json_data_qz_2
    elif num == 3:
        json_data = json_data_3
    elif num == 4:
        json_data = json_data_4
    elif num == 5:
        json_data = json_data_qz_5
    elif num == 6:
        json_data = json_data_qz_6
    elif num == 7:
        json_data = json_data_qz_7
    else:
        json_data = json_data_qz_1

    headers = {
        **COMMON_HEADERS,
        'authorization': f'Bearer {token}',
        'privy-id-token': token_id,
        'x-apollo-operation-name': 'VerifyActivity',
    }

    response_data = await _make_request(
        session,
        'https://api.deform.cc/',
        headers=headers,
        json_data=json_data,
        proxy=proxy,
        operation_name='verify_activity_quiz'
    )

    # Проверка ответа
    if isinstance(response_data, dict):
        logger.debug(f"Verify quiz {num} response: {response_data}")
        if 'errors' in response_data and response_data['errors']:
            logger.warning(f"API error for quiz {num}: {response_data['errors']}")
            return 'ALREADY_COMPLETED'
        if 'data' in response_data and 'verifyActivity' in response_data['data']:
            record = response_data['data']['verifyActivity'].get('record', {})
            status = record.get('status')
            if status == 'COMPLETED':
                return 'COMPLETED'
            elif status == 'ALREADY_COMPLETED':
                return 'ALREADY_COMPLETED'

    logger.error(f"Failed to verify quiz {num}, unknown API response: {response_data}")
    return 'ERROR'
