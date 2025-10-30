"""Streamlit dashboard for PawChain Capital credit insights."""

from __future__ import annotations

import json
from typing import Any, Optional

import pandas as pd
import streamlit as st
from web3 import Web3
from web3.exceptions import Web3Exception


# ---------------------------------------------------------------------------
# 1. Page configuration & headline
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Credit Dashboard", page_icon="🐶", layout="wide")

st.title("🐶 PawChain Capital Credit Dashboard")
st.caption("Blend on-chain balances with invoice performance to underwrite faster.")


# ---------------------------------------------------------------------------
# 2. Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.title("User Input")
default_rpc = "https://rpc.testnet.arc.network"
rpc_url = st.sidebar.text_input("Arc RPC URL", value=default_rpc, help="Paste your Arc (or compatible) RPC endpoint.")
wallet_address = st.sidebar.text_input("Wallet Address", help="0x... address you want to score")
uploaded_file = st.sidebar.file_uploader("Upload invoices CSV", type=["csv"], help="Include at least a 'days_to_payment' column for analytics.")

with st.sidebar.expander("Credit Registry Contract (optional)"):
    contract_address = st.text_input("Contract Address", placeholder="0x…")
    abi_text = st.text_area(
        "Contract ABI",
        placeholder="Paste ABI JSON array here if you want to pull credit score data.",
        height=160,
    )


# ---------------------------------------------------------------------------
# 3. Web3 helpers
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_web3_client(rpc: str) -> Optional[Web3]:
    if not rpc:
        return None
    client = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
    return client if client.is_connected() else None


def get_balance(web3_client: Web3, addr: str) -> float:
    raw = web3_client.eth.get_balance(Web3.to_checksum_address(addr))
    return raw / (10**18)  # Adjust decimals if USDC is bridged with different precision


w3 = get_web3_client(rpc_url)
if rpc_url and not w3:
    st.warning("Unable to connect to the provided RPC endpoint. Double-check the URL or network status.")


# ---------------------------------------------------------------------------
# 4. Fetch on-chain data
# ---------------------------------------------------------------------------
balance: Optional[float] = None
if wallet_address and w3:
    with st.spinner("Fetching wallet balance from Arc..."):
        try:
            balance = get_balance(w3, wallet_address)
        except ValueError:
            st.error("Wallet address is invalid. Please enter a valid checksum address.")
        except Web3Exception as exc:  # pragma: no cover - UI feedback only
            st.error(f"Failed to fetch balance: {exc}")
        except Exception as exc:  # pragma: no cover - UI feedback only
            st.error(f"Unexpected error fetching balance: {exc}")


# ---------------------------------------------------------------------------
# 5. Process uploaded invoice data
# ---------------------------------------------------------------------------
df: Optional[pd.DataFrame] = None
avg_delay: Optional[float] = None
invoice_count: Optional[int] = None

if uploaded_file is not None:
    with st.spinner("Parsing invoice data..."):
        try:
            df = pd.read_csv(uploaded_file)
            invoice_count = len(df)
            if "days_to_payment" in df.columns:
                avg_delay = float(df["days_to_payment"].mean())
            else:
                st.info("CSV loaded, but 'days_to_payment' column not found. Add it to compute payment delay.")
        except Exception as exc:  # pragma: no cover - UI feedback only
            st.error(f"Failed to parse CSV: {exc}")


# ---------------------------------------------------------------------------
# 6. Optional smart-contract interaction
# ---------------------------------------------------------------------------
credit_score: Optional[Any] = None
if w3 and wallet_address and contract_address and abi_text:
    try:
        abi = json.loads(abi_text)
        contract = w3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=abi)
        credit_score = contract.functions.scores(Web3.to_checksum_address(wallet_address)).call()
    except json.JSONDecodeError:
        st.error("ABI is not valid JSON. Please paste a valid ABI array.")
    except ValueError as exc:  # includes bad addresses
        st.error(f"Contract interaction error: {exc}")
    except Web3Exception as exc:  # pragma: no cover - UI feedback only
        st.error(f"Unable to query contract: {exc}")
    except Exception as exc:  # pragma: no cover - UI feedback only
        st.error(f"Unexpected contract error: {exc}")


# ---------------------------------------------------------------------------
# 7. Display metrics & visuals
# ---------------------------------------------------------------------------
col1, col2, col3 = st.columns(3)

with col1:
    if balance is not None:
        col1.metric("Wallet Balance (USDC)", f"{balance:.2f}")
    elif wallet_address:
        col1.write("Balance unavailable")
    else:
        col1.write("Enter wallet address")

with col2:
    if avg_delay is not None:
        col2.metric("Avg Payment Delay (days)", f"{avg_delay:.1f}")
    elif df is not None:
        col2.write("Add 'days_to_payment' column")
    else:
        col2.write("Upload invoice CSV")

with col3:
    if invoice_count is not None:
        col3.metric("Invoice Count", invoice_count)
    else:
        col3.write("Invoices pending")


st.markdown("## 🐶 Doggo Credit Assistant")
if balance is not None and avg_delay is not None:
    st.success("Great job! Your on-chain balance is healthy and your payment delays are low — you’re scoring well!")
else:
    st.write("Enter a wallet address and upload payment data to unlock your full credit picture.")


if credit_score is not None:
    st.markdown("### Credit Registry Snapshot")
    st.json({"creditScore": credit_score[0], "metadata": credit_score[1:], "raw": credit_score})


# ---------------------------------------------------------------------------
# 8. Additional visuals
# ---------------------------------------------------------------------------
if df is not None:
    st.markdown("### Invoice Overview")
    st.dataframe(df)

    numeric_cols = df.select_dtypes(include=["number"]).columns
    if len(numeric_cols) > 0:
        with st.expander("Numeric column trends"):
            st.line_chart(df[numeric_cols])


# ---------------------------------------------------------------------------
# 9. Footer / how-to
# ---------------------------------------------------------------------------
st.divider()
st.markdown(
    """
    **Need next steps?**
    - Run locally with `streamlit run app.py`
    - Replace the placeholder contract details with your deployed `CreditScoreRegistry` or `CreditLineManager`
    - Adjust token decimals to match the Arc asset you’re tracking (USDC = 6 decimals on most chains)
    - Deploy to Streamlit Cloud, Heroku, or your preferred hosting when production ready
    """
)

