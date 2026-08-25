"""Проверка, что MCP-сервер поднимается и все инструменты зарегистрированы."""

from mcp_server.server import mcp

EXPECTED_TOOLS = {
    "vats_auth_status",
    "vats_auth_start",
    "vats_auth_complete",
    "vats_auth_import",
    "vats_contacts_list",
    "vats_contact_add",
    "vats_contact_update",
    "vats_contact_delete",
    "vats_contact_group_add",
    "vats_contact_group_delete",
    "vats_domain_users",
    "vats_users_list",
    "vats_groups_list",
    "vats_calls_history",
    "vats_call_protocol",
    "vats_call_record",
    "vats_balance",
    "vats_numbers",
    "vats_settings",
    "vats_proxy",
}


async def test_tools_registered():
    tools = {t.name for t in await mcp.list_tools()}
    assert EXPECTED_TOOLS <= tools, f"Не хватает инструментов: {EXPECTED_TOOLS - tools}"


async def test_tools_have_descriptions():
    for tool in await mcp.list_tools():
        assert tool.description, f"У инструмента {tool.name} нет описания"
