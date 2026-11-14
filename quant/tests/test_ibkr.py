import pytest
from pydantic import ValidationError

from quant_engine.config import Settings
from quant_engine.connectors.ibkr import IBKRConnectionError, IBKRConnector


class DisconnectedIB:
    def isConnected(self) -> bool:
        return False

    async def connectAsync(self, *args, **kwargs):
        raise OSError("connection refused")


@pytest.mark.asyncio
async def test_connection_failure_is_reported_without_leaking_details() -> None:
    connector = IBKRConnector(Settings(), ib=DisconnectedIB())

    with pytest.raises(IBKRConnectionError, match="configured TWS or IB Gateway"):
        await connector.connect()


def test_configuration_rejects_live_ibkr_ports() -> None:
    with pytest.raises(ValidationError, match="paper-trading port"):
        Settings(ibkr_port=7496)
