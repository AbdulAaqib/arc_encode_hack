from __future__ import annotations

from typing import Any, Dict, Optional

import os
import streamlit as st

from .wallet_connect_component import connect_wallet


DEFAULT_SESSION_KEY = "connected_wallet_info"
ARC_CHAIN_ID_ENV = "ARC_CHAIN_ID"


def _resolve_chain_id() -> Optional[int]:
    raw = os.getenv(ARC_CHAIN_ID_ENV)
    if not raw:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        return None


def render_wallet_page() -> None:
    """Render the wallet connect page that bridges MetaMask to Streamlit."""

    st.title("🔐 Wallet Connect")
    st.caption("Use your injected wallet (MetaMask, Rabby, etc.) directly inside Streamlit.")

    chain_id = _resolve_chain_id()
    if chain_id is None:
        st.error(
            "Environment variable `ARC_CHAIN_ID` is not set or invalid. Set it to a decimal or hex chain ID "
            "before using the wallet connector."
        )
        st.stop()

    col_left, col_right = st.columns([2, 1])
    with col_right:
        st.subheader("Session State")
        stored: Dict[str, Any] = st.session_state.get(DEFAULT_SESSION_KEY, {})  # type: ignore[assignment]
        if stored.get("isConnected") and stored.get("address"):
            st.success(f"Cached address: {stored['address']}")
            st.json(stored)
        else:
            st.info("No wallet cached yet.")

    with col_left:
        st.subheader("Connect")
        st.caption(f"Required chain ID: `{chain_id}` (from ARC_CHAIN_ID)")

        wallet_info = connect_wallet(key="wallet_connect", require_chain_id=chain_id)

        st.write(":ledger: Component payload")
        st.json(wallet_info)

        if wallet_info and wallet_info.get("isConnected"):
            st.success(f"Connected wallet: {wallet_info.get('address')}")

            if st.button("Store in session", key="cache_wallet"):
                st.session_state[DEFAULT_SESSION_KEY] = wallet_info
                st.toast("Wallet cached in session_state", icon="✅")
        else:
            st.warning("Connect with MetaMask using the button above.")

    st.divider()
    st.subheader("Tips")
    st.markdown(
        """
        - Install an injected wallet such as MetaMask in your browser.
        - Ensure `ARC_CHAIN_ID` matches the network you expect the wallet to use.
        - Use the JSON payload above from Python to drive downstream logic (contract calls, gating, etc.).
        """
    )
