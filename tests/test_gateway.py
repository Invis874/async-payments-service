import pytest

from app.consumer.gateway import process_payment


@pytest.mark.asyncio
async def test_process_payment_returns_bool(mocker):
    mocker.patch("asyncio.sleep", return_value=None)
    result = await process_payment()
    assert isinstance(result, bool)