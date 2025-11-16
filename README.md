# SnifferBank — Identity‑based Lending on Arc (SBT + Pool MVP)

A credit‑infrastructure platform on Arc that enables underserved creators and SMBs to access stable‑coin loans using verifiable on‑chain credentials and a unified credit score derived from on‑chain and off‑chain data sources.

---

## What it does

- Builds an identity‑based lending flow on Arc using a non‑transferable Soul‑Bound Token (SBT) as a verifiable credential.
- Computes a SnifferBank Credit Score by merging on‑chain reputation (wallet history, transaction activity/volume) with off‑chain cash‑flow signals (uploaded bank statements and financial documents).
- Unlocks USDC working‑capital loans for eligible borrowers through an integrated lending pool.
- Ships with SBT credential system, credit line manager, and lending pool with deposit/withdrawal functionality.

---

## How it works (end‑to‑end)

1) Wallet Connection & Verification
- User connects a wallet in the Streamlit app and (optionally) signs a message for ownership.

2) Off‑Chain + On‑Chain Data Collection
- On‑chain: fetch wallet metrics (wallet age, transaction activity/volume, behavior patterns).
- Off‑chain: user uploads bank statements or provides simplified income/expenses; system extracts net income, consistency, and spend patterns.
- A unified SnifferBank Credit Score is computed from both sources.

3) Credential Issuance (SBT)
- If the user meets criteria, the smart contract mints a non‑transferable SBT to their wallet representing their credit identity and current score.

4) Lender Pool & Deposits
- Lenders deposit USDC into the LendingPool contract and receive deposit entries tracked by the contract. Liquidity is used for borrower draws; lenders can withdraw their deposits (subject to lock periods and available balance).
- The LendingPool contract manages deposits, loan issuance, repayments, and lender withdrawals with built-in SBT gating for borrowers.

5) Borrower Loan Draw
- Borrower sees eligibility based on their SBT credential and credit score (e.g., "You're eligible for X USDC").
- Borrower initiates loan draw; the LendingPool contract verifies eligibility (SBT gating enforced on‑chain) and available liquidity. On success, USDC is transferred to the borrower's wallet.

6) Borrower Repayment
- Borrower repays (principal, or principal+return if enabled) and contract updates their outstanding balance/status.

7) Lender Withdrawal & Returns
- As borrowers repay, the pool liquidity is replenished. Lenders can withdraw their deposits (subject to lock periods) for underlying USDC. Returns accrue as borrowers repay loans with interest.

8) Arc‑specific advantages
- USDC‑native fees and predictable costs, making working‑capital lending practical. Sub‑second finality and EVM‑compatibility.

---

## Why SnifferBank Matters

- **Identity‑based lending**: The SBT acts as a verifiable on‑chain credential for credit identity, enabling trustless access to credit.
- **Reputation‑driven credit**: Combines on‑chain wallet behavior with off‑chain cash‑flow analysis, moving beyond pure crypto collateral requirements.
- **Stable‑coin native**: All loans are USDC‑denominated on Arc, providing stable value and predictable terms.
- **Full credit market**: Complete lender/borrower ecosystem with deposit management, loan issuance, repayments, and returns distribution.
- **Accessibility**: Enables underserved creators and SMBs to access working capital loans without traditional banking barriers.

---

## Key Architecture & Contracts

- `TrustMintSBT.sol` (deployed)
  - Non‑transferable ERC‑721 (ERC‑5192 semantics); one token per wallet.
  - Functions: `issueScore(borrower, value)`, `revokeScore(borrower)`, `getScore(borrower) -> (value, timestamp, valid)`, `hasSbt(wallet)`, `tokenIdOf(wallet)`.
  - Metadata via `tokenURI`; transfer/burn disabled; owner is the issuer.
  - Acts as the core credential system for SnifferBank's identity-based lending.

- `CreditLineManager.sol` (deployed)
  - Owner‑managed USDC credit lines with `limit`, `drawn`, `interestRate` (bps), and `availableCredit` view.
  - `draw(borrower, amount)` transfers USDC held by the contract; `repay(borrower, amount)` returns USDC to the contract.
  - Provides alternative credit line management separate from the lending pool.

- `CreditScoreRegistry.sol` (optional alternative)
  - Minimal issuer‑only registry maintaining an updatable score mapping. Kept for compatibility and comparison with the SBT approach.

- `LendingPool.sol` (deployed)
  - Full-featured lending pool with lender deposits, borrower loans, repayments, and withdrawals.
  - On‑chain verification of borrower SBT credentials and scores.
  - Lender deposit tracking with lock periods and withdrawal controls.
  - Loan state management: Active, Repaid, Defaulted.
  - Actions include: DEPOSIT, WITHDRAW, OPEN_LOAN, REPAY, CHECK_DEFAULT, UNBAN.

---

## Repository Layout

- `blockchain_code/`
  - `src/TrustMintSBT.sol` — SBT credential with score binding for identity verification.
  - `src/CreditLineManager.sol` — Credit lines: create, draw, repay, close, and `availableCredit`.
  - `src/CreditScoreRegistry.sol` — Optional minimal registry for score tracking.
  - `src/LendingPool.sol` — Full lending pool with deposits, loans, repayments, and withdrawals.
  - `out/` — Foundry build artifacts (ABIs under the `abi` field of each JSON).
  - `lib/` — OpenZeppelin contracts and dependencies.
- `streamlit/`
  - `src/frontend/app.py` — Streamlit entrypoint (auto‑loads `.env` at repo root).
  - `src/frontend/components/` — Chatbot, MCP Tools, wallet connect, CCTP bridge, verification, and UI helpers.
    - `chatbot_lib/` — Chatbot infrastructure with Azure OpenAI integration.
    - `mcp_lib/` — MCP (Model Context Protocol) tools and utilities.
    - `toolkit_lib/` — Bridge tools, pool tools, SBT tools, and transaction helpers.
    - `verification/` — Eligibility checking, on-chain/off-chain verification, and score calculation.
- `blockchain_runner/` — Python utilities for executing blockchain commands and managing limits.
- `compile_contracts.py` — Contract compilation helper script.
- `run_blockchain_terminal_commands.py` — Terminal command executor for blockchain operations.

---

## Quickstart

Prereqs
- Python 3.12
- Foundry (forge, cast). Install: `curl -L https://foundry.paradigm.xyz | bash && foundryup`

1) Clone + setup Python deps

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2) Create `.env` at repo root

The Streamlit app auto‑loads `.env` from the repo root.

```bash
# Azure OpenAI (Chatbot + parsing)
AZURE_OPENAI_ENDPOINT=your_azure_openai_endpoint
AZURE_OPENAI_KEY=your_azure_openai_key
AZURE_OPENAI_API_VERSION=2024-06-01
AZURE_OPENAI_CHAT_DEPLOYMENT=your_deployment_name  # e.g., gpt-4o-mini / gpt-4o

# Arc RPC + signing key (LOCAL DEV ONLY — never commit or share)
ARC_TESTNET_RPC_URL=https://arc-testnet.example.rpc  # replace with actual Arc testnet RPC
PRIVATE_KEY=0xabc123...  # test-only key with minimal funds

# SBT contract (used by the MCP Tools UI and SnifferBank platform)
SBT_ADDRESS=0xYourDeployedSbt
TRUSTMINT_SBT_ABI_PATH=blockchain_code/out/TrustMintSBT.sol/TrustMintSBT.json

# Lending Pool contract
LENDING_POOL_ADDRESS=0xYourLendingPool
LENDING_POOL_ABI_PATH=blockchain_code/out/LendingPool.sol/LendingPool.json

# Optional gas tuning
ARC_USDC_DECIMALS=6
ARC_GAS_LIMIT=200000
ARC_GAS_PRICE_GWEI=1

# Optional advanced
CREDIT_LINE_MANAGER_ADDRESS=0xYourCreditLineManager
CREDIT_LINE_MANAGER_ABI_PATH=blockchain_code/out/CreditLineManager.sol/CreditLineManager.json

# Optional: Polygon/CCTP bridge (for cross-chain transfers)
POLYGON_RPC=https://polygon-rpc.example
POLYGON_PRIVATE_KEY=0xabc123...  # for automatic Polygon minting
```

3) Build and (optionally) deploy contracts with Foundry

```bash
cd blockchain_code
forge build
# run tests
forge test -vv

# Deploy SBT (constructor: name, symbol, initialOwner)
forge create src/TrustMintSBT.sol:TrustMintSBT \
  --rpc-url "$ARC_TESTNET_RPC_URL" \
  --private-key "$PRIVATE_KEY" \
  --constructor-args "SnifferBank SBT" SNFSBT 0xYourOwnerAddress

# Deploy LendingPool (constructor: IERC20 stablecoin, ITrustMintSBT sbt, initialOwner)
# Use Arc testnet USDC address for the first argument and deployed SBT address for the second
forge create src/LendingPool.sol:LendingPool \
  --rpc-url "$ARC_TESTNET_RPC_URL" \
  --private-key "$PRIVATE_KEY" \
  --constructor-args 0xArcTestnetUSDC 0xYourDeployedSbt 0xYourOwnerAddress

# Optional: Deploy CreditLineManager (constructor: IERC20 stablecoin, initialOwner)
# Use Arc testnet USDC address for the first argument, then set CREDIT_LINE_MANAGER_ADDRESS in .env
forge create src/CreditLineManager.sol:CreditLineManager \
  --rpc-url "$ARC_TESTNET_RPC_URL" \
  --private-key "$PRIVATE_KEY" \
  --constructor-args 0xArcTestnetUSDC 0xYourOwnerAddress
```

Copy the deployed addresses into `.env` (`SBT_ADDRESS`, `LENDING_POOL_ADDRESS`, and optionally `CREDIT_LINE_MANAGER_ADDRESS`).

4) Interact via CLI (SBT)

```bash
# Read score + SBT
cast call $SBT_ADDRESS "hasSbt(address)(bool)" 0xSomeWallet --rpc-url $ARC_TESTNET_RPC_URL
cast call $SBT_ADDRESS "getScore(address)(uint256,uint256,bool)" 0xSomeWallet --rpc-url $ARC_TESTNET_RPC_URL

# Issue / revoke (owner only)
cast send $SBT_ADDRESS "issueScore(address,uint256)" 0xSomeWallet 720 \
  --rpc-url $ARC_TESTNET_RPC_URL --private-key $PRIVATE_KEY
cast send $SBT_ADDRESS "revokeScore(address)" 0xSomeWallet \
  --rpc-url $ARC_TESTNET_RPC_URL --private-key $PRIVATE_KEY
```

5) Run the Streamlit app

```bash
# From repo root (ensure your .env is in the repo root)
source venv/bin/activate
streamlit run streamlit/src/frontend/app.py
```

Navigate via the sidebar:
- Intro — SnifferBank project overview and setup reminders
- Chatbot — Azure OpenAI‑powered assistant with document uploads for off‑chain financial data parsing
- MCP Tools — interactive panel for SBT operations (hasSbt, getScore, issueScore, revokeScore) and lending pool actions
- Wallet Connect — wallet connection and verification interface

### Owner USDC Tools (Same-Chain & CCTP)

- Configure `ARC_TESTNET_RPC_URL`, `LENDING_POOL_ADDRESS`, and either `ARC_OWNER_PRIVATE_KEY` or `PRIVATE_KEY` in `.env`.
- In the Streamlit "Wallet Connect" or "MCP Tools" pages you get two distinct flows:
  - **ARC → ARC** — calls `transferUsdcOnArc` so the lending pool owner can pay any ARC wallet directly (no CCTP involved).
  - **ARC → Polygon (CCTP)** — calls `prepareCctpBridge` to move USDC from the pool into the owner wallet, then the app signs the Circle Token Messenger `depositForBurn` so the funds can mint on Polygon (or other supported chains) after attestation.
- The UI surfaces three ARC transactions (prepare, optional allowance approval, burn) plus the Polygon mint payload. If you set `POLYGON_RPC` and `POLYGON_PRIVATE_KEY`, the app will automatically submit the Polygon `receiveMessage` call; otherwise, it exposes the message & attestation along with a MetaMask “Mint on Polygon” button so you can send the transaction manually.
- Polygon minting (automatic or manual) still requires the Polygon signer to hold test MATIC for gas.

---

## Demo Flow

1. **Wallet Connection & Eligibility Check**
   - Connect a wallet via the Streamlit UI
   - System checks eligibility based on on-chain and off-chain data

2. **SBT Issuance & Scoring**
   - Issue a credit score for a borrower (issuer‑only) → `issueScore(borrower, value)` stores value/timestamp, sets valid=true, and mints SBT if missing.
   - Revoke a score (issuer‑only) → `revokeScore(borrower)` sets valid=false; SBT remains non‑transferable and bound.

3. **Lender Operations (LendingPool)**
   - Lender deposits USDC into the pool via `deposit(amount)`
   - Track deposit entries and available balance

4. **Borrower Operations (LendingPool)**
   - Borrower with valid SBT opens a loan: `openLoan(principal, repaymentDeadline)`
   - Borrower repays: `repay(loanId, amount)`
   - System checks for defaults: `checkDefaultAndBan(loanId)`

5. **Alternative: CreditLineManager (Optional)**
   - Create a credit line (owner‑only): `createCreditLine(borrower, limit, interestBps)`
   - Draw: `draw(borrower, amount)` (transfers USDC held by the contract)
   - Repay: `repay(borrower, amount)` (requires ERC20 allowance)

---

## Lending Pool Design

The `LendingPool.sol` contract implements a comprehensive lending system:

- **Deposits**: Lenders deposit USDC into the pool and receive deposit entries tracked by the contract. Each deposit has a lock period before withdrawal is allowed.
- **Loans**: Borrowers with valid SBT credentials can open loans from the pool. Loan amounts are subject to available liquidity and borrower eligibility.
- **Repayments**: Borrowers repay loans (principal plus interest), which replenishes the pool liquidity.
- **Withdrawals**: Lenders can withdraw their deposits (after lock period) for underlying USDC. Returns accrue as borrowers repay with interest.
- **Default Management**: The system tracks loan states and can mark loans as defaulted, banning borrowers who fail to repay by the deadline.
- **Transparency**: On‑chain metrics reveal utilization, borrower behavior, loan status, and pool health.

The pool enforces SBT gating on-chain, ensuring only eligible borrowers can access loans.

---

## Arc‑specific notes

- USDC‑native gas model enables predictable fees and smooth UX.
- EVM‑compatible, sub‑second finality; easy integration with wallets and tooling.
- Replace example RPC endpoints and USDC addresses with Arc testnet values for your environment.

---

## Business Model (Concept)

- Underwriting fee or a small interest spread.
- Tiered services (higher scores → larger limits, lower rates).
- Partnerships with SMB/creator tools for distribution and richer data.
- Optional aggregated, privacy‑preserving insights for lenders/insurers.

---

## Roadmap

- ✅ Core SBT credential system with score binding
- ✅ Lending pool with deposits, loans, and repayments
- ✅ On-chain SBT gating for borrower eligibility
- 🔄 Enhanced score model: deeper on‑chain analytics + off‑chain bank data, invoices, platform revenue
- 🔄 Advanced risk management: automated interest accrual, late fees, delinquency handling
- 🔄 Lender dashboard with analytics and yield metrics
- 🔄 Third‑party verifier interface using the SBT credential
- 🔄 Gas sponsorship for SBT mint/update flows
- 🔄 Multi-chain support expansion beyond Arc
- 🔄 Integration with additional data providers for richer credit assessment

---

## Notes & Disclaimers

- This repository is for hackathon/demo use on testnets. Do not use real keys or funds.
- Use a dedicated test wallet with minimal funds for `PRIVATE_KEY`.
- RPC endpoints and USDC addresses differ per network; replace placeholders with actual Arc testnet values.
