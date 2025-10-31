# 🧠 arc_encode_hack  
### Stablecoin Lending with Off-Chain Trust — Powered by Arc, Circle, and LLM Orchestration

---

## 🚀 Overview

**arc_encode_hack** is an experimental **on-chain credit platform** built for the **Arc Hackathon**.  
It allows individuals and small businesses to access **USDC credit lines** — combining **on-chain credit logic** with **off-chain trust assessment**.

The **Arc blockchain** executes and settles credit agreements, while an **LLM + MCP agent** evaluates off-chain data to score borrowers, automate approvals, and manage repayments.

> **Smart credit lines on-chain — powered by stablecoins, scored by intelligence.**

---

## 🏗️ Architecture

| Layer | Description |
|-------|--------------|
| **Arc Blockchain** | Hosts the core credit smart contracts for open, draw, repay, and close operations. |
| **Circle API Integration** | Moves real USDC between borrower and protocol wallets using Circle’s sandbox environment. |
| **LLM + MCP Intelligence Layer** | Gathers and interprets off-chain data (KYC, wallet history, business reputation, social data) to compute a dynamic trust score. |
| **Backend (FastAPI)** | Bridges the blockchain, Circle API, and the LLM agent. Handles workflow orchestration. |
| **Frontend (React)** | Lightweight borrower dashboard for applications, balance views, and repayments. |
| **Database** | Caches off-chain signals and maintains borrower score history (SQLite/Postgres). |

---

## 🔁 Credit Lifecycle

1. **Application**  
   Borrower provides wallet and identity data.  
   The LLM agent automatically collects off-chain trust signals.

2. **Scoring**  
   AI computes a composite **Trust Score** that reflects both blockchain and off-chain activity.

3. **Approval**  
   If score ≥ threshold, an Arc smart contract opens a USDC credit line with encoded limits and terms.

4. **Drawdown**  
   Borrower requests funds → Circle API sends USDC → transaction logged on Arc chain.

5. **Repayment**  
   Repayments are made in USDC. Arc verifies and settles balances on-chain.

6. **Monitoring**  
   The LLM agent tracks repayments, overdue behavior, and can adjust limits dynamically.

---

## 🧩 Core Components

| Component | Stack |
|------------|--------|
| Smart Contracts | Solidity + Arc SDK |
| Off-Chain Agent | LLM + MCP Tools |
| Backend | Python + FastAPI + Web3.py |
| Frontend | React + Tailwind |
| APIs | Circle Sandbox APIs |
| Database | SQLite / Postgres |
