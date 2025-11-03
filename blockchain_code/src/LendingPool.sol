// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @notice Minimal interface for TrustMintSBT used for gating
interface ITrustMintSBT {
    function hasSbt(address wallet) external view returns (bool);
    function getScore(address wallet) external view returns (uint256 value, uint256 timestamp, bool valid);
}

/**
 * @title LendingPool
 * @notice Holds stablecoin liquidity deposited by lenders and issues loans to borrowers.
 *         Tracks loans with due dates; bans borrowers who fail to repay on time.
 *         Optional SBT/score gating via TrustMintSBT.
 */
contract LendingPool is Ownable {
    using SafeERC20 for IERC20;

    // --- Immutable token ---
    IERC20 public immutable STABLECOIN; // e.g., USDC

    // --- Optional credential gating ---
    address public trustMintSbt; // set to 0x0 to disable SBT/score checks
    uint256 public minScoreToBorrow = 600; // simple threshold for demo; adjust per policy

    // --- Lender accounting ---
    mapping(address => uint256) public deposits;     // total deposited by lender
    mapping(address => uint256) public withdrawals;  // total withdrawn by lender
    uint256 public totalDeposits;                    // sum of deposits
    // Global lock: lenders can withdraw only after this lock duration from their last deposit
    uint256 public depositLockSeconds;              // 0 means no lock
    mapping(address => uint256) public lockedUntil; // per-lender unlock timestamp

    // --- Borrower loan state ---
    struct Loan {
        uint256 principal;   // total principal issued
        uint256 outstanding; // amount still due
        uint256 startTime;   // loan start
        uint256 dueTime;     // deadline to repay
        bool active;         // true while outstanding > 0
    }
    mapping(address => Loan) public loans;

    // --- Ban list ---
    mapping(address => bool) public banned;

    // --- Events ---
    event Deposited(address indexed lender, uint256 amount);
    event Withdrawn(address indexed lender, uint256 amount);
    event LoanOpened(address indexed borrower, uint256 principal, uint256 startTime, uint256 dueTime);
    event LoanRepaid(address indexed borrower, uint256 amount, uint256 remaining);
    event BorrowerBanned(address indexed borrower);
    event BorrowerUnbanned(address indexed borrower);

    constructor(IERC20 _stablecoin, address initialOwner) Ownable(initialOwner) {
        STABLECOIN = _stablecoin;
    }

    // --- Configuration ---
    function setTrustMintSbt(address sbt) external onlyOwner {
        trustMintSbt = sbt; // set 0x0 to disable gating
    }

    function setMinScoreToBorrow(uint256 newMinScore) external onlyOwner {
        minScoreToBorrow = newMinScore;
    }

    function setDepositLockSeconds(uint256 seconds_) external onlyOwner {
        depositLockSeconds = seconds_;
    }

    // --- Lender actions ---

    /**
     * @notice Lender deposits stablecoin to the pool.
     * @dev Requires ERC20 allowance set to this contract.
     */
    function deposit(uint256 amount) external {
        require(amount > 0, "amount=0");
        deposits[msg.sender] += amount;
        totalDeposits += amount;
        STABLECOIN.safeTransferFrom(msg.sender, address(this), amount);
        // Update per-lender lock timestamp
        if (depositLockSeconds > 0) {
            uint256 newLockedUntil = block.timestamp + depositLockSeconds;
            if (newLockedUntil > lockedUntil[msg.sender]) {
                lockedUntil[msg.sender] = newLockedUntil;
            }
        }
        emit Deposited(msg.sender, amount);
    }

    /**
     * @notice Withdraw lender funds that are not currently lent out.
     * @dev Withdrawals are limited by available liquidity in the contract.
     */
    function withdraw(uint256 amount) external {
        require(amount > 0, "amount=0");
        // Enforce global lock if configured
        require(block.timestamp >= lockedUntil[msg.sender], "locked");
        uint256 netBalance = deposits[msg.sender] - withdrawals[msg.sender];
        require(netBalance >= amount, "insufficient lender balance");
        uint256 available = availableLiquidity();
        require(available >= amount, "insufficient pool liquidity");

        withdrawals[msg.sender] += amount;
        STABLECOIN.safeTransfer(msg.sender, amount);
        emit Withdrawn(msg.sender, amount);
    }

    // --- Borrower actions ---

    /**
     * @notice Open a loan for `borrower` and send principal immediately.
     * @dev Simple demo policy: callable by owner/governance. Optional SBT+score gating.
     *      The pool must have sufficient liquid funds to issue the loan.
     * @param borrower The borrower wallet address
     * @param principal Principal amount to issue (in token decimals)
     * @param termSeconds Time until due, in seconds
     */
    function openLoan(address borrower, uint256 principal, uint256 termSeconds) external onlyOwner {
        require(!banned[borrower], "borrower banned");
        require(principal > 0, "principal=0");
        require(termSeconds > 0, "term=0");
        require(availableLiquidity() >= principal, "insufficient liquidity");

        // Optional credential gating
        if (trustMintSbt != address(0)) {
            ITrustMintSBT sbt = ITrustMintSBT(trustMintSbt);
            require(sbt.hasSbt(borrower), "no SBT");
            (uint256 score,, bool valid) = sbt.getScore(borrower);
            require(valid, "invalid score");
            require(score >= minScoreToBorrow, "score too low");
        }

        Loan storage loan = loans[borrower];
        require(!loan.active || loan.outstanding == 0, "active loan exists");

        loan.principal = principal;
        loan.outstanding = principal;
        loan.startTime = block.timestamp;
        loan.dueTime = block.timestamp + termSeconds;
        loan.active = true;

        STABLECOIN.safeTransfer(borrower, principal);
        emit LoanOpened(borrower, principal, loan.startTime, loan.dueTime);
    }

    /**
     * @notice Repay part or all of the outstanding loan.
     * @dev Borrower must approve this contract to pull funds.
     */
    function repay(uint256 amount) external {
        Loan storage loan = loans[msg.sender];
        require(loan.active, "no active loan");
        require(amount > 0, "amount=0");
        require(amount <= loan.outstanding, "repay > outstanding");

        STABLECOIN.safeTransferFrom(msg.sender, address(this), amount);
        loan.outstanding -= amount;

        if (loan.outstanding == 0) {
            loan.active = false;
            // Borrower may be banned due to lateness; owner can unban later if policy allows.
        }

        emit LoanRepaid(msg.sender, amount, loan.outstanding);
    }

    /**
     * @notice Check and mark borrower as banned if past due and still outstanding.
     * @dev Can be called by anyone (UI or automation) to enforce ban policy.
     */
    function checkDefaultAndBan(address borrower) external {
        Loan storage loan = loans[borrower];
        if (loan.active && block.timestamp > loan.dueTime && loan.outstanding > 0 && !banned[borrower]) {
            banned[borrower] = true;
            emit BorrowerBanned(borrower);
        }
    }

    /**
     * @notice Owner can unban a borrower (e.g., after full repayment or appeal).
     */
    function unban(address borrower) external onlyOwner {
        require(banned[borrower], "not banned");
        banned[borrower] = false;
        emit BorrowerUnbanned(borrower);
    }

    // --- Views ---

    function isBanned(address borrower) external view returns (bool) {
        return banned[borrower];
    }

    function getLoan(address borrower) external view returns (Loan memory) {
        return loans[borrower];
    }

    function lenderBalance(address lender) external view returns (uint256) {
        return deposits[lender] - withdrawals[lender];
    }

    function getLockedUntil(address lender) external view returns (uint256) {
        return lockedUntil[lender];
    }

    function availableLiquidity() public view returns (uint256) {
        // Liquidity equals current token balance; outstanding loans reduce balance because funds left the contract
        return STABLECOIN.balanceOf(address(this));
    }
}
