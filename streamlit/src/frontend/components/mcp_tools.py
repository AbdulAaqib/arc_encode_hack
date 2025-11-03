"""MCP Tools: Direct MCP Tool Tester for TrustMintSBT and LendingPool."""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict

import streamlit as st
from web3 import Web3
from web3.contract import Contract

from .config import (
    ARC_RPC_ENV,
    SBT_ADDRESS_ENV,
    TRUSTMINT_SBT_ABI_PATH_ENV,
    PRIVATE_KEY_ENV,
    GAS_LIMIT_ENV,
    GAS_PRICE_GWEI_ENV,
    USDC_DECIMALS_ENV,
    LENDING_POOL_ADDRESS_ENV,
    LENDING_POOL_ABI_PATH_ENV,
    USDC_ADDRESS_ENV,
    USDC_ABI_PATH_ENV,
    get_sbt_address,
)
from .web3_utils import get_web3_client, load_contract_abi
from .toolkit import build_llm_toolkit, build_lending_pool_toolkit


def _render_tool_runner(tools_schema: list[Dict[str, Any]], function_map: Dict[str, Callable[..., str]], key_prefix: str) -> None:
    st.subheader("Run a tool")

    if not tools_schema:
        st.info("No MCP tools available. Check contract addresses and ABI paths.")
        return

    tool_names = [entry["function"]["name"] for entry in tools_schema]
    selected = st.selectbox("Choose a tool", tool_names, key=f"{key_prefix}_tool_select")

    schema = next(item for item in tools_schema if item["function"]["name"] == selected)
    parameters = schema["function"].get("parameters", {})
    props = parameters.get("properties", {})
    required = set(parameters.get("required", []))

    inputs: Dict[str, Any] = {}
    for name, details in props.items():
        field_type = details.get("type", "string")
        label = f"{name} ({field_type})"
        default = details.get("default")

        if field_type == "integer":
            value = st.number_input(label, value=int(default or 0), step=1, key=f"{key_prefix}_param_{selected}_{name}")
            inputs[name] = int(value)
        elif field_type == "number":
            value = st.number_input(label, value=float(default or 0), key=f"{key_prefix}_param_{selected}_{name}")
            inputs[name] = float(value)
        elif field_type == "boolean":
            inputs[name] = st.checkbox(label, value=bool(default) if default is not None else False, key=f"{key_prefix}_param_{selected}_{name}")
        elif field_type == "array":
            raw = st.text_area(
                f"{label} (comma separated)",
                value=", ".join(default or []) if isinstance(default, list) else "",
                key=f"{key_prefix}_param_{selected}_{name}"
            )
            inputs[name] = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            inputs[name] = st.text_input(
                label,
                value=str(default) if default is not None else "",
                key=f"{key_prefix}_param_{selected}_{name}"
            )

    if st.button("Run MCP tool", key=f"{key_prefix}_run_tool"):
        missing = [param for param in required if not inputs.get(param)]
        if missing:
            st.error(f"Missing required parameters: {', '.join(missing)}")
            return

        handler = function_map.get(selected)
        if handler is None:
            st.error("Selected tool does not have an implementation.")
            return

        with st.spinner(f"Running `{selected}`..."):
            try:
                result = handler(**inputs)
            except TypeError as exc:
                st.error(f"Parameter mismatch: {exc}")
                return
            except Exception as exc:
                st.error(f"Tool execution failed: {exc}")
                return

        st.success("Tool completed")
        try:
            parsed = json.loads(result) if isinstance(result, str) else result
            st.json(parsed)
        except Exception:
            st.write(result if isinstance(result, str) else json.dumps(result))


def render_mcp_tools_page() -> None:
    st.title("🧪 Direct MCP Tool Tester")
    st.caption("Run MCP tools for TrustMintSBT and LendingPool.")

    # Env config
    rpc_url = os.getenv(ARC_RPC_ENV)
    private_key_env = os.getenv(PRIVATE_KEY_ENV)
    default_gas_limit = int(os.getenv(GAS_LIMIT_ENV, "200000"))
    gas_price_gwei = os.getenv(GAS_PRICE_GWEI_ENV, "1")

    # Signing role selector (without editing .env)
    st.divider()
    st.subheader("Signing Role")
    role = st.selectbox("Select role for signing", ["Read-only", "Owner", "Lender", "Borrower"], index=0, key="signing_role")
    with st.expander("Private keys for roles (stored only in session)"):
        owner_pk = st.text_input("Owner PRIVATE_KEY", value=private_key_env or "", type="password", key="pk_owner")
        lender_pk = st.text_input("Lender PRIVATE_KEY", value="", type="password", key="pk_lender")
        borrower_pk = st.text_input("Borrower PRIVATE_KEY", value="", type="password", key="pk_borrower")
    effective_private_key = None
    if role == "Owner":
        effective_private_key = owner_pk or None
    elif role == "Lender":
        effective_private_key = lender_pk or None
    elif role == "Borrower":
        effective_private_key = borrower_pk or None

    # Build web3
    w3 = get_web3_client(rpc_url)
    status_col, _, _ = st.columns([2, 0.2, 2])
    with status_col:
        if w3:
            st.success(f"Connected to Arc RPC: {rpc_url}")
        else:
            st.error("RPC unavailable. Set `ARC_TESTNET_RPC_URL` in `.env` and ensure the endpoint is reachable.")
        if role == "Read-only":
            st.info("Read-only mode selected; transactions are disabled.")
        elif not effective_private_key:
            st.info(f"No PRIVATE_KEY provided for selected role '{role}'. Transactions are disabled.")
    if not w3:
        st.stop()

    st.divider()
    st.header("TrustMint SBT Tools")

    sbt_address, _ = get_sbt_address()
    sbt_abi_path = os.getenv(TRUSTMINT_SBT_ABI_PATH_ENV)
    if not sbt_address or not sbt_abi_path:
        st.warning("Set `SBT_ADDRESS` and `TRUSTMINT_SBT_ABI_PATH` in `.env` to enable SBT tools.")
    else:
        abi = load_contract_abi(sbt_abi_path)
        try:
            sbt_contract: Contract = w3.eth.contract(address=Web3.to_checksum_address(sbt_address), abi=abi)  # type: ignore[arg-type]
            tools_schema, function_map = build_llm_toolkit(
                w3=w3,
                contract=sbt_contract,
                token_decimals=0,
                private_key=effective_private_key,
                default_gas_limit=default_gas_limit,
                gas_price_gwei=gas_price_gwei,
            )
            _render_tool_runner(tools_schema, function_map, key_prefix="sbt")
        except Exception as exc:
            st.error(f"Unable to build SBT contract instance: {exc}")

    st.divider()
    st.header("LendingPool Tools")

    pool_address = os.getenv(LENDING_POOL_ADDRESS_ENV)
    pool_abi_path = os.getenv(LENDING_POOL_ABI_PATH_ENV)
    usdc_address = os.getenv(USDC_ADDRESS_ENV)
    usdc_abi_path = os.getenv(USDC_ABI_PATH_ENV)
    usdc_decimals = int(os.getenv(USDC_DECIMALS_ENV, "6"))

    if not pool_address or not pool_abi_path:
        st.warning("Set `LENDING_POOL_ADDRESS` and `LENDING_POOL_ABI_PATH` in `.env` to enable LendingPool tools.")
        return

    pool_abi = load_contract_abi(pool_abi_path)
    usdc_abi = load_contract_abi(usdc_abi_path) if usdc_abi_path else None

    try:
        pool_contract: Contract = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=pool_abi)  # type: ignore[arg-type]
    except Exception as exc:
        st.error(f"Unable to build LendingPool contract instance: {exc}")
        return

    tools_schema, function_map = build_lending_pool_toolkit(
        w3=w3,
        pool_contract=pool_contract,
        usdc_address=usdc_address,
        usdc_abi=usdc_abi,
        usdc_decimals=usdc_decimals,
        private_key=effective_private_key,
        default_gas_limit=default_gas_limit,
        gas_price_gwei=gas_price_gwei,
    )

    _render_tool_runner(tools_schema, function_map, key_prefix="pool")

