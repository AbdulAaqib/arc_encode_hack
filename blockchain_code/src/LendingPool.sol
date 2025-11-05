// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {SafeCast} from "@openzeppelin/contracts/utils/math/SafeCast.sol";

/// @notice Minimal interface for TrustMintSBT used for gating
interface ITrustMintSBT {
    function hasSbt(address wallet) external view returns (bool);
    function getScore(address wallet) external view returns (uint256 value, uint256 timestamp, bool valid);
}

/**
 * @title LendingPool
 * @notice Accepts native-token deposits (USDC-denominated on Arc), issues loans, and enforces timed lender withdrawals.
 *         Funds are transferred into the pool contract immediately; borrowers repay in native token as well.
 */
contract LendingPool is Ownable, ReentrancyGuard {
    // --- Errors ---
    error DepositAmountZero();
    error DepositValueMismatch(uint256 expected, uint256 actual);
    error DepositAmountTooLarge();
    error WithdrawAmountZero();
    error WithdrawExceedsDeposits();
    error DepositEntryDepleted();
    error DepositLocked(uint256 unlockTime);
    error PoolLiquidityInsufficient(uint256 requested, uint256 available);
    error TransferToLenderFailed();
    error BorrowerBannedError(address borrower);
    error LoanPrincipalZero();
    error LoanTermZero();
    error BorrowerMissingSbt(address borrower);
    error BorrowerScoreInvalid(address borrower);
    error BorrowerScoreTooLow(address borrower, uint256 score, uint256 minScore);
    error BorrowerHasUnpaidLoan(address borrower, uint256 outstanding);
    error TransferToBorrowerFailed();
    error NoActiveLoan();
    error RepayAmountZero();
    error RepayValueMismatch(uint256 expected, uint256 actual);
    error RepayAmountTooLarge(uint256 amount, uint256 outstanding);
    error RepayExactAmountRequired(uint256 required);
    error BorrowerNotBanned(address borrower);
    // --- Optional credential gating ---
    address public trustMintSbt; // set to 0x0 to disable SBT/score checks
    uint256 public minScoreToBorrow = 600;

    // --- Lender accounting ---
    struct DepositEntry {
        uint128 amount;     // remaining amount in this entry (wei)
        uint64 timestamp;   // deposit time
    }

    mapping(address => DepositEntry[]) private _deposits;
    mapping(address => uint256) public nextWithdrawalIndex; // first entry with remaining balance
    mapping(address => uint256) public totalDeposited;
    mapping(address => uint256) public totalWithdrawn;
    uint256 public totalDeposits; // total amount ever deposited minus withdrawn

    uint256 public depositLockSeconds; // global lock duration applied to each deposit entry

    // --- Borrower loan state ---
    struct Loan {
        uint256 principal;
        uint256 outstanding;
        uint256 startTime;
        uint256 dueTime;
        bool active;
    }
    mapping(address => Loan) public loans;

    // --- Ban list ---
    mapping(address => bool) public banned;

    // --- Events ---
    event Deposited(address indexed lender, uint256 amount, uint256 timestamp);
    event Withdrawn(address indexed lender, uint256 amount);
    event LoanOpened(address indexed borrower, uint256 principal, uint256 startTime, uint256 dueTime);
    event LoanRepaid(address indexed borrower, uint256 amount, uint256 remaining);
    event BorrowerBanned(address indexed borrower);
    event BorrowerUnbanned(address indexed borrower);
    event TrustMintSbtUpdated(address indexed sbt);
    event MinScoreUpdated(uint256 minScore);
    event DepositLockUpdated(uint256 lockSeconds);

    constructor(address initialOwner) Ownable(initialOwner) {}

    // --- Configuration ---
    function setTrustMintSbt(address sbt) external onlyOwner {
        trustMintSbt = sbt;
        emit TrustMintSbtUpdated(sbt);
    }

    function setMinScoreToBorrow(uint256 newMinScore) external onlyOwner {
        minScoreToBorrow = newMinScore;
        emit MinScoreUpdated(newMinScore);
    }

    function setDepositLockSeconds(uint256 seconds_) external onlyOwner {
        depositLockSeconds = seconds_;
        emit DepositLockUpdated(seconds_);
    }

    // --- Lender actions ---

    /**
     * @notice Deposit native token (USDC on Arc) into the pool.
     * @param amount Amount in wei; must equal msg.value.
     */
    function deposit(uint256 amount) external payable nonReentrant {
        if (amount == 0) revert DepositAmountZero();
        if (msg.value != amount) revert DepositValueMismatch(amount, msg.value);
        if (amount > type(uint128).max) revert DepositAmountTooLarge();

        uint128 amount128 = SafeCast.toUint128(amount);
        uint64 timestamp64 = SafeCast.toUint64(block.timestamp);

        _deposits[msg.sender].push(DepositEntry({amount: amount128, timestamp: timestamp64}));
        totalDeposited[msg.sender] += amount;
        totalDeposits += amount;

        emit Deposited(msg.sender, amount, block.timestamp);
    }

    /**
     * @notice Withdraw unlocked funds that have completed the lock period.
     * @param amount Amount to withdraw in wei.
     */
    function withdraw(uint256 amount) external nonReentrant {
        if (amount == 0) revert WithdrawAmountZero();
        uint256 remaining = amount;
        uint256 idx = nextWithdrawalIndex[msg.sender];
        DepositEntry[] storage entries = _deposits[msg.sender];

        while (remaining > 0) {
            if (idx >= entries.length) revert WithdrawExceedsDeposits();
            DepositEntry storage entry = entries[idx];
            if (entry.amount == 0) revert DepositEntryDepleted();
            if (block.timestamp < entry.timestamp + depositLockSeconds) {
                revert DepositLocked(entry.timestamp + depositLockSeconds);
            }

            uint256 entryAmount = entry.amount;
            if (entryAmount > remaining) {
                entry.amount = SafeCast.toUint128(entryAmount - remaining);
                remaining = 0;
            } else {
                remaining -= entryAmount;
                entry.amount = 0;
                idx++;
            }
        }

        nextWithdrawalIndex[msg.sender] = idx;
        totalWithdrawn[msg.sender] += amount;
        totalDeposits -= amount;

        uint256 available = address(this).balance;
        if (available < amount) revert PoolLiquidityInsufficient(amount, available);
        (bool sent, ) = msg.sender.call{value: amount}("");
        if (!sent) revert TransferToLenderFailed();

        emit Withdrawn(msg.sender, amount);
    }

    // --- Borrower actions ---

    /**
     * @notice Issue a loan to `borrower` and send principal immediately. Callable by owner/governance.
     * @param borrower Borrower wallet
     * @param principal Principal in wei
     * @param termSeconds Loan duration in seconds
     */
    function openLoan(address borrower, uint256 principal, uint256 termSeconds) external onlyOwner nonReentrant {
        if (banned[borrower]) revert BorrowerBannedError(borrower);
        if (principal == 0) revert LoanPrincipalZero();
        if (termSeconds == 0) revert LoanTermZero();
        uint256 available = address(this).balance;
        if (available < principal) revert PoolLiquidityInsufficient(principal, available);

        if (trustMintSbt != address(0)) {
            ITrustMintSBT sbt = ITrustMintSBT(trustMintSbt);
            if (!sbt.hasSbt(borrower)) revert BorrowerMissingSbt(borrower);
            (uint256 score,, bool valid) = sbt.getScore(borrower);
            if (!valid) revert BorrowerScoreInvalid(borrower);
            if (score < minScoreToBorrow) revert BorrowerScoreTooLow(borrower, score, minScoreToBorrow);
        }

        Loan storage loan = loans[borrower];
        if (loan.active && loan.outstanding != 0) revert BorrowerHasUnpaidLoan(borrower, loan.outstanding);

        loan.principal = principal;
        loan.outstanding = principal;
        loan.startTime = block.timestamp;
        loan.dueTime = block.timestamp + termSeconds;
        loan.active = true;

        (bool sent, ) = payable(borrower).call{value: principal}("");
        if (!sent) revert TransferToBorrowerFailed();

        emit LoanOpened(borrower, principal, loan.startTime, loan.dueTime);
    }

    /**
     * @notice Repay part or all of an outstanding loan by sending native token.
     * @param amount Amount in wei; must equal msg.value.
     */
    function repay(uint256 amount) external payable nonReentrant {
        Loan storage loan = loans[msg.sender];
        if (!loan.active) revert NoActiveLoan();
        if (amount == 0) revert RepayAmountZero();
        if (msg.value != amount) revert RepayValueMismatch(amount, msg.value);
        if (amount > loan.outstanding) revert RepayAmountTooLarge(amount, loan.outstanding);
        if (amount != loan.outstanding) revert RepayExactAmountRequired(loan.outstanding);

        loan.outstanding = 0;
        loan.active = false;

        emit LoanRepaid(msg.sender, amount, 0);
    }

    // --- Ban management ---
    function checkDefaultAndBan(address borrower) external {
        Loan storage loan = loans[borrower];
        if (loan.active && block.timestamp > loan.dueTime && loan.outstanding > 0 && !banned[borrower]) {
            banned[borrower] = true;
            emit BorrowerBanned(borrower);
        }
    }

    function unban(address borrower) external onlyOwner {
        if (!banned[borrower]) revert BorrowerNotBanned(borrower);
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
        return totalDeposited[lender] - totalWithdrawn[lender];
    }

    function previewWithdraw(address lender) public view returns (uint256 unlockable) {
        DepositEntry[] storage entries = _deposits[lender];
        uint256 idx = nextWithdrawalIndex[lender];
        uint256 len = entries.length;
        uint256 current = block.timestamp;
        uint256 lockPeriod = depositLockSeconds;

        while (idx < len) {
            DepositEntry storage entry = entries[idx];
            if (entry.amount == 0) {
                idx++;
                continue;
            }
            if (current < entry.timestamp + lockPeriod) {
                break;
            }
            unlockable += entry.amount;
            idx++;
        }
    }

    function getDeposits(address lender) external view returns (DepositEntry[] memory) {
        return _deposits[lender];
    }

    function loanStatus(address borrower)
        external
        view
        returns (
            bool active,
            uint256 principal,
            uint256 outstanding,
            uint256 startTime,
            uint256 dueTime,
            bool bannedStatus
        )
    {
        Loan storage loan = loans[borrower];
        return (loan.active, loan.principal, loan.outstanding, loan.startTime, loan.dueTime, banned[borrower]);
    }

    function lenderStatus(address lender)
        external
        view
        returns (
            uint256 totalDeposited_,
            uint256 totalWithdrawn_,
            uint256 balance,
            uint256 unlockable
        )
    {
        totalDeposited_ = totalDeposited[lender];
        totalWithdrawn_ = totalWithdrawn[lender];
        balance = totalDeposited_ - totalWithdrawn_;
        unlockable = previewWithdraw(lender);
    }

    function canOpenLoan(address borrower, uint256 principal)
        external
        view
        returns (bool ok, string memory reason)
    {
        if (principal == 0) return (false, "Principal must be greater than zero");
        if (banned[borrower]) return (false, "Borrower is banned");

        uint256 available = address(this).balance;
        if (available < principal) return (false, "Insufficient pool liquidity");

        if (trustMintSbt != address(0)) {
            ITrustMintSBT sbt = ITrustMintSBT(trustMintSbt);
            if (!sbt.hasSbt(borrower)) return (false, "Borrower lacks required SBT");
            (uint256 score,, bool valid) = sbt.getScore(borrower);
            if (!valid) return (false, "Borrower score invalid");
            if (score < minScoreToBorrow) return (false, "Borrower score below minimum");
        }

        Loan storage loan = loans[borrower];
        if (loan.active && loan.outstanding != 0) return (false, "Borrower has an active loan");

        return (true, "OK");
    }

    function availableLiquidity() public view returns (uint256) {
        return address(this).balance;
    }
}
