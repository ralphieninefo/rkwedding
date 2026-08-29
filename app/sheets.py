"""Header-aware Google Sheets REST integration."""

from typing import Any
from urllib.parse import quote

import httpx


class GoogleSheetsClient:
    """Read and update tracker tabs without hard-coded column letters."""

    def __init__(
        self,
        access_token: str,
        spreadsheet_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.transport = transport
        self.headers = {"Authorization": f"Bearer {access_token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url="https://sheets.googleapis.com/v4",
            headers=self.headers,
            timeout=30,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}

    async def get_rows(self, sheet_name: str) -> list[dict[str, str]]:
        escaped_range = quote(f"'{sheet_name}'!A:ZZ", safe="")
        data = await self._request(
            "GET",
            f"/spreadsheets/{self.spreadsheet_id}/values/{escaped_range}",
        )
        values = data.get("values", [])
        if not values:
            return []
        headers = [str(value).strip() for value in values[0]]
        return [
            {
                header: str(row[index]).strip() if index < len(row) else ""
                for index, header in enumerate(headers)
                if header
            }
            | {"_row_number": str(row_number)}
            for row_number, row in enumerate(values[1:], start=2)
        ]

    async def find_row(
        self, sheet_name: str, column: str, value: str
    ) -> dict[str, str] | None:
        target = value.casefold().strip()
        return next(
            (
                row
                for row in await self.get_rows(sheet_name)
                if row.get(column, "").casefold().strip() == target
            ),
            None,
        )

    async def update_row(
        self,
        sheet_name: str,
        row_number: int,
        updates: dict[str, Any],
    ) -> None:
        rows = await self.get_rows(sheet_name)
        if not rows:
            raise ValueError(f"Sheet {sheet_name!r} has no data rows or headers.")
        headers = [key for key in rows[0] if key != "_row_number"]
        data = []
        for column, value in updates.items():
            if column not in headers:
                continue
            index = headers.index(column) + 1
            letters = ""
            while index:
                index, remainder = divmod(index - 1, 26)
                letters = chr(65 + remainder) + letters
            data.append(
                {
                    "range": f"'{sheet_name}'!{letters}{row_number}",
                    "values": [[value]],
                }
            )
        if data:
            await self._request(
                "POST",
                f"/spreadsheets/{self.spreadsheet_id}/values:batchUpdate",
                json={"valueInputOption": "USER_ENTERED", "data": data},
            )

    async def append_row(self, sheet_name: str, values: list[Any]) -> None:
        escaped_range = quote(f"'{sheet_name}'!A:ZZ", safe="")
        await self._request(
            "POST",
            f"/spreadsheets/{self.spreadsheet_id}/values/{escaped_range}:append",
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json={"values": [values]},
        )

    async def get_state(self, sheet_name: str, key: str) -> str | None:
        row = await self.find_row(sheet_name, "Key", key)
        return row.get("Value") if row else None

    async def set_state(self, sheet_name: str, key: str, value: str) -> None:
        row = await self.find_row(sheet_name, "Key", key)
        if row:
            await self.update_row(sheet_name, int(row["_row_number"]), {"Value": value})
        else:
            await self.append_row(sheet_name, [key, value])
