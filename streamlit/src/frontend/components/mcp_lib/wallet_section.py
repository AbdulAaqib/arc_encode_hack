from __future__ import annotations

import json
from time import time
from typing import Any, Dict

import streamlit as st
from web3 import Web3

from ..wallet import DEFAULT_SESSION_KEY
from ..wallet_connect_component import wallet_command
from .rerun import st_rerun


def render_wallet_section(mm_state: Dict[str, Any], w3: Web3, key_prefix: str, selected: str) -> None:
    mm_payload = mm_state.get("metamask", {})
    tx_req = mm_payload.get("tx_request")
    if isinstance(tx_req, str):
        try:
            tx_req = json.loads(tx_req)
        except json.JSONDecodeError:
            st.warning("Tool provided tx_request that is not valid JSON.")
            tx_req = None
    action = mm_payload.get("action") or "eth_sendTransaction"
    from_address = mm_payload.get("from")
    chain_id = mm_payload.get("chainId")
    if chain_id is None:
        st.warning("Chain ID not provided by tool; ensure your wallet is connected to the correct network.")

    cached = st.session_state.get(DEFAULT_SESSION_KEY, {})
    preferred_address = cached.get("address") if isinstance(cached, dict) else None
    if from_address:
        preferred_address = from_address
        mm_state.setdefault("wallet_address", from_address)

    mm_state.setdefault("pending_command", None)
    mm_state.setdefault("last_result", None)
    mm_state.setdefault("last_value", None)

    pending = mm_state.get("pending_command")
    component_key = f"wallet_headless_{key_prefix}_{selected}"
    command = pending.get("command") if isinstance(pending, dict) else None
    command_payload = pending.get("payload") if isinstance(pending, dict) else None
    command_sequence = pending.get("sequence") if isinstance(pending, dict) else None

    command_payload = {"tx_request": tx_req, "action": action}
    if from_address:
        command_payload["from"] = from_address

    component_value = wallet_command(
        key=component_key,
        command=command,
        command_payload=command_payload,
        command_sequence=command_sequence,
        require_chain_id=chain_id,
        tx_request=tx_req,
        action=action,
        preferred_address=preferred_address,
        autoconnect=True,
    )

    if component_value is not None:
        mm_state["last_value"] = component_value
        if (
            isinstance(pending, dict)
            and isinstance(component_value, dict)
            and component_value.get("commandSequence") == pending.get("sequence")
        ):
            mm_state["last_result"] = component_value
            mm_state["pending_command"] = None
            addr = component_value.get("address")
            if addr:
                mm_state["wallet_address"] = addr
            chain = component_value.get("chainId")
            if chain:
                mm_state["wallet_chain"] = chain

    status_cols = st.columns(2)
    with status_cols[0]:
        wallet_addr = mm_state.get("wallet_address") or preferred_address
        if wallet_addr:
            st.info(f"Cached wallet: {wallet_addr}")
        else:
            st.info("No wallet connected yet.")
    with status_cols[1]:
        if chain_id:
            st.info(f"Required chain: {chain_id}")
        if from_address:
            st.caption(f"Requested signer: {from_address}")

    if pending:
        st.warning("Command sent to MetaMask. Confirm in your wallet …")

    btn_cols = st.columns(3)
    if btn_cols[0].button("Connect wallet", key=f"btn_connect_{key_prefix}_{selected}"):
        mm_state["pending_command"] = {
            "command": "connect",
            "payload": {},
            "sequence": int(time() * 1000),
        }
        st.session_state[f"mm_state_{key_prefix}_{selected}"] = mm_state
        st_rerun()

    if btn_cols[1].button("Switch network", key=f"btn_switch_{key_prefix}_{selected}"):
        mm_state["pending_command"] = {
            "command": "switch_network",
            "payload": {"require_chain_id": chain_id},
            "sequence": int(time() * 1000),
        }
        st.session_state[f"mm_state_{key_prefix}_{selected}"] = mm_state
        st_rerun()

    send_disabled = tx_req is None
    if btn_cols[2].button("Send transaction", key=f"btn_send_{key_prefix}_{selected}", disabled=send_disabled):
        mm_state["pending_command"] = {
            "command": "send_transaction",
            "payload": {"tx_request": tx_req, "action": action},
            "sequence": int(time() * 1000),
        }
        st.session_state[f"mm_state_{key_prefix}_{selected}"] = mm_state
        st_rerun()

    last_result = mm_state.get("last_result")
    if isinstance(last_result, dict):
        tx_hash = last_result.get("txHash")
        error_msg = last_result.get("error")
        status = last_result.get("status")
        addr_for_session = last_result.get("address") or mm_state.get("wallet_address")
        chain_for_session = last_result.get("chainId") or mm_state.get("wallet_chain")
        if addr_for_session:
            st.session_state.setdefault(DEFAULT_SESSION_KEY, {})
            if isinstance(st.session_state[DEFAULT_SESSION_KEY], dict):
                st.session_state[DEFAULT_SESSION_KEY]["address"] = addr_for_session
        if chain_for_session:
            st.session_state.setdefault(DEFAULT_SESSION_KEY, {})
            if isinstance(st.session_state[DEFAULT_SESSION_KEY], dict):
                st.session_state[DEFAULT_SESSION_KEY]["chainId"] = chain_for_session
        if error_msg:
            st.error(f"MetaMask command failed: {error_msg}")
        else:
            if status:
                st.success(f"MetaMask status: {status}")
            if tx_hash:
                st.success(f"Transaction sent: {tx_hash}")
                explorer_url = f"https://testnet.arcscan.app/tx/{tx_hash}"
                st.markdown(f"[View on Arcscan]({explorer_url})", help="Opens Arcscan for the transaction")
                with st.spinner("Waiting for receipt…"):
                    try:
                        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                        st.caption("Transaction receipt")
                        st.json(
                            {
                                "transactionHash": receipt.get("transactionHash").hex()
                                if receipt.get("transactionHash")
                                else tx_hash,
                                "status": receipt.get("status"),
                                "blockNumber": receipt.get("blockNumber"),
                                "gasUsed": receipt.get("gasUsed"),
                                "cumulativeGasUsed": receipt.get("cumulativeGasUsed"),
                            }
                        )
                    except Exception as exc:
                        st.warning(f"Unable to fetch receipt yet: {exc}")

    with st.expander("Transaction request", expanded=False):
        if tx_req is not None:
            st.json(tx_req)
        else:
            st.write("(none)")

    with st.expander("Latest component payload", expanded=False):
        st.write(component_value)

    if st.button("Clear MetaMask state", key=f"clear_mm_{key_prefix}_{selected}"):
        st.session_state.pop(f"mm_state_{key_prefix}_{selected}", None)
        st_rerun()
