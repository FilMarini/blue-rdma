import ClientServer :: *;
import FIFOF :: *;
import GetPut :: *;
import PAClib :: *;

import Controller :: *;
import DataTypes :: *;
import Headers :: *;
import PrimUtils :: *;
import SpecialFIFOF :: *;
import Settings :: *;
import Utils :: *;

typedef enum {
    RETRY_HANDLER_RESET_TIMEOUT,
    RETRY_HANDLER_RESET_RETRY_CNT_AND_TIMEOUT
} ResetRetryCntAndTimeOutReq deriving(Bits, Eq, FShow);

typedef enum {
    RETRY_HANDLER_TIMEOUT_RETRY,
    RETRY_HANDLER_TIMEOUT_ERR
} TimeOutNotification deriving(Bits, Eq, FShow);

typedef struct {
    WorkReqID        wrID;
    PSN              retryStartPSN;
    RetryReason      retryReason;
    Maybe#(RnrTimer) retryRnrTimer;
} RetryReq deriving(Bits);

typedef enum {
    RETRY_HANDLER_RECV_RETRY_REQ,
    RETRY_HANDLER_RETRY_LIMIT_EXC
} RetryResp deriving(Bits, Eq, FShow);

interface RetryHandleSQ;
    method Bool hasRetryErr();
    method Bool isRetryDone();
    method Bool isRetrying();
    method Action resetRetryCntAndTimeOutBySQ(
        ResetRetryCntAndTimeOutReq resetReq
    );
    method ActionValue#(TimeOutNotification) notifyTimeOut2SQ();
    interface Server#(RetryReq, RetryResp) srvPort;
endinterface

typedef enum {
    RETRY_HANDLE_ST_NOT_RETRY,
    RETRY_HANDLE_ST_START_PRE_RETRY,
    RETRY_HANDLE_ST_RNR_CHECK,
    RETRY_HANDLE_ST_RNR_WAIT,
    RETRY_HANDLE_ST_CHECK_PARTIAL_RETRY_WR,
    RETRY_HANDLE_ST_MODIFY_PARTIAL_RETRY_WR,
    RETRY_HANDLE_ST_START_RETRY,
    RETRY_HANDLE_ST_WAIT_RETRY_DONE
} RetryHandleState deriving(Bits, Eq, FShow);

typedef enum {
    RETRY_CNTRL_ST_NOT_RETRY,
    RETRY_CNTRL_ST_RETRY_LIMIT_EXC,
    // RETRY_CNTRL_ST_RESET_RETRY_CNT,
    // RETRY_CNTRL_ST_RECV_RETRY_REQ,
    RETRY_CNTRL_ST_INIT_RETRY,
    RETRY_CNTRL_ST_WAIT_RETRY_DONE
} RetryCntrlState deriving(Bits, Eq, FShow);

module mkRetryHandleSQ#(
    Controller cntrl,
    Bool pendingWorkReqNotEmpty,
    ScanCntrl#(PendingWorkReq) pendingWorkReqScanCntrl
)(RetryHandleSQ);
    // Output FIFO for PipeOut
    FIFOF#(ResetRetryCntAndTimeOutReq)     resetReqQ <- mkFIFOF;
    FIFOF#(TimeOutNotification) timeOutNotificationQ <- mkFIFOF;
    FIFOF#(RetryReq)   retryReqQ <- mkFIFOF;
    FIFOF#(RetryResp) retryRespQ <- mkFIFOF;

    // Pipeline FIFO
    FIFOF#(Bool)                           resetTimeOutQ <- mkFIFOF;
    FIFOF#(Bool)                          resetRetryCntQ <- mkFIFOF;
    FIFOF#(Bool)                         timeOutTriggerQ <- mkFIFOF;
    FIFOF#(Maybe#(RetryReq))          retryNotificationQ <- mkFIFOF;
    FIFOF#(Maybe#(RetryReq))                retryActionQ <- mkFIFOF;
    FIFOF#(Maybe#(RetryReason))          updateRetryCntQ <- mkFIFOF;
    FIFOF#(Tuple2#(Bool, RetryReason)) prepareRetryRespQ <- mkFIFOF;

    Reg#(RnrWaitCycleCnt)    rnrWaitCntReg <- mkRegU;
    Reg#(Bool)         isRnrWaitCntZeroReg <- mkRegU;
    Reg#(TimeOutCycleCnt)    timeOutCntReg <- mkRegU;
    Reg#(Bool) isTimeOutCntHighPartZeroReg <- mkRegU;
    Reg#(Bool)  isTimeOutCntLowPartZeroReg <- mkRegU;
    // Reg#(Bool)         isTimeOutCntZeroReg <- mkRegU;
    Reg#(Bool)           disableTimeOutReg <- mkRegU;
    Reg#(Bool)          disableRetryCntReg <- mkRegU;

    Reg#(RetryReason)    retryReasonReg <- mkRegU;
    Reg#(WorkReqID)   retryWorkReqIdReg <- mkRegU;
    Reg#(PSN)          retryStartPsnReg <- mkRegU;
    Reg#(PSN)                psnDiffReg <- mkRegU;
    Reg#(RnrTimer)     retryRnrTimerReg <- mkRegU;
    Reg#(RetryCnt)          retryCntReg <- mkRegU;
    Reg#(RetryCnt)            rnrCntReg <- mkRegU;

    Reg#(RetryCntrlState)  retryCntrlStateReg[2] <- mkCReg(2, RETRY_CNTRL_ST_NOT_RETRY);
    Reg#(RetryHandleState) retryHandleStateReg <- mkReg(RETRY_HANDLE_ST_NOT_RETRY);
    Reg#(Bool)             pauseRetryHandleReg <- mkReg(False);

    (* no_implicit_conditions, fire_when_enabled *)
    rule resetAndClear if (cntrl.isReset);
        pendingWorkReqScanCntrl.clear;

        resetReqQ.clear;
        timeOutNotificationQ.clear;
        retryReqQ.clear;
        retryRespQ.clear;

        resetTimeOutQ.clear;
        resetRetryCntQ.clear;
        timeOutTriggerQ.clear;
        retryNotificationQ.clear;
        retryActionQ.clear;
        updateRetryCntQ.clear;
        prepareRetryRespQ.clear;

        pauseRetryHandleReg   <= False;
        retryCntrlStateReg[0] <= RETRY_CNTRL_ST_NOT_RETRY;
        retryHandleStateReg   <= RETRY_HANDLE_ST_NOT_RETRY;

        // $display("time=%0t: reset and clear retry handler", $time);
    endrule

    let notRetrying = retryCntrlStateReg[0] == RETRY_CNTRL_ST_NOT_RETRY;
    let retryErr    = retryCntrlStateReg[0] == RETRY_CNTRL_ST_RETRY_LIMIT_EXC;
    let retryingWR  = retryHandleStateReg == RETRY_HANDLE_ST_WAIT_RETRY_DONE;

    function Bool retryCntExceedLimit(RetryReason retryReason);
        return case (retryReason)
            RETRY_REASON_RNR     : isZero(rnrCntReg);
            RETRY_REASON_SEQ_ERR ,
            RETRY_REASON_IMPLICIT,
            RETRY_REASON_TIMEOUT : isZero(retryCntReg);
            // RETRY_REASON_NOT_RETRY
            default              : False;
        endcase;
    endfunction

    function Action decRetryCntByReason(RetryReason retryReason);
        action
            case (retryReason)
                RETRY_REASON_SEQ_ERR ,
                RETRY_REASON_IMPLICIT,
                RETRY_REASON_TIMEOUT : begin
                    if (!disableRetryCntReg) begin
                        if (!isZero(retryCntReg)) begin
                            retryCntReg <= retryCntReg - 1;
                        end
                    end
                end
                RETRY_REASON_RNR: begin
                    if (!disableRetryCntReg) begin
                        if (!isZero(rnrCntReg)) begin
                            rnrCntReg <= rnrCntReg - 1;
                        end
                    end
                end
                default: begin
                    immFail(
                        "unreachible case in decRetryCntByReason() @ mkRetryHandleSQ",
                        $format("retryReason=", fshow(retryReason))
                    );
                end
            endcase
        endaction
    endfunction

    function Action resetRetryCntInternal();
        action
            retryCntReg        <= cntrl.getMaxRetryCnt;
            rnrCntReg          <= cntrl.getMaxRnrCnt;
            disableRetryCntReg <= cntrl.getMaxRetryCnt == fromInteger(valueOf(INFINITE_RETRY));
        endaction
    endfunction

    function Action resetTimeOutCntInternal();
        action
            timeOutCntReg       <= fromInteger(getTimeOutValue(cntrl.getMaxTimeOut));
            disableTimeOutReg   <= isZero(cntrl.getMaxTimeOut);
            // isTimeOutCntZeroReg <= False;
            isTimeOutCntHighPartZeroReg <= False;
            isTimeOutCntLowPartZeroReg  <= False;
            // timeOutNotificationQ.clear;
            // $display("time=%0t: cntrl.getMaxTimeOut=%0d", $time, origMaxTimeOutReg);
        endaction
    endfunction

    rule initRetryCntAndTimeOutTimer if (cntrl.isInit);
        resetRetryCntInternal;
        resetTimeOutCntInternal;
        timeOutNotificationQ.clear;

        // $display("time=%0t: init RetryCnt and TimeOutTimer", $time);
    endrule

    //                     stopScanQ, \
    //                     initRetry, \
    //                     waitRetryFinish, \
    //                     startPreRetry, \
    //                     rnrCheck, \
    //                     rnrWait, \
    //                     modifyPartialRetryWR, \
    //                     startRetry, \
    //                     waitRetryDone" *)
    // (* conflict_free = "recvResetReq, \
    //                     recvRetryReq, \
    //                     checkTimeOut, \
    //                     handleNotifiedRetryAndTimeOut, \
    //                     handleRetryAction, \
    //                     handleRetryCntUpdate, \
    //                     sendRetryResp" *)
    // TODO: add conflict_free, no_implicit_conditions and fire_when_enabled attributes
    rule recvResetReq if (cntrl.isRTS);
        let resetReq = resetReqQ.first;
        resetReqQ.deq;

        case (resetReq)
            RETRY_HANDLER_RESET_TIMEOUT: begin
                let resetTimeOut = True;
                resetTimeOutQ.enq(resetTimeOut);
            end
            RETRY_HANDLER_RESET_RETRY_CNT_AND_TIMEOUT: begin
                let resetTimeOut = True;
                resetTimeOutQ.enq(resetTimeOut);
                let resetRetryCnt = True;
                resetRetryCntQ.enq(resetRetryCnt);
            end
            default: begin
                immFail(
                    "unreachible case @ mkRetryHandleSQ",
                    $format(
                        "resetReq=", fshow(resetReq)
                    )
                );
            end
        endcase
    endrule

    rule recvRetryReq if (cntrl.isRTS);
        let maybeRetryReq = tagged Invalid;
        let shouldResetRetryCnt = False;
        if (resetRetryCntQ.notEmpty) begin
            resetRetryCntQ.deq;
            shouldResetRetryCnt = True;
        end

        let hasNotifiedRetry = False;
        if (retryReqQ.notEmpty) begin
            maybeRetryReq = tagged Valid retryReqQ.first;
            retryReqQ.deq;

            hasNotifiedRetry = True;
        end

        // hasNotifiedRetry has higher priority than shouldResetRetryCnt
        if (hasNotifiedRetry || shouldResetRetryCnt) begin
            // immAssert(
            //     hasNotifiedRetry && shouldResetRetryCnt,
            //     "hasNotifiedRetry && shouldResetRetryCnt assertion @ mkRetryHandleSQ",
            //     $format(
            //         "hasNotifiedRetry=", fshow(hasNotifiedRetry),
            //         " and shouldResetRetryCnt=", fshow(shouldResetRetryCnt),
            //         " cannot both be true"
            //     )
            // );

            retryNotificationQ.enq(maybeRetryReq);
        end
    endrule

    rule checkTimeOut if (cntrl.isRTS);
        let hasResetTimeOutReq = resetTimeOutQ.notEmpty;
        if (hasResetTimeOutReq) begin
            resetTimeOutQ.deq;
        end

        if (hasResetTimeOutReq || !notRetrying) begin // Disable timeout when retry
            resetTimeOutCntInternal;
        end
        else if (
            !disableTimeOutReg     &&
            pendingWorkReqNotEmpty && // Enable timeout when having pending WR
            notRetrying               // Enable timeout when not retry
        ) begin
            // if (isTimeOutCntZeroReg) begin
            if (isTimeOutCntHighPartZeroReg && isTimeOutCntLowPartZeroReg) begin
                let triggerTimeOut = True;
                timeOutTriggerQ.enq(triggerTimeOut);
                resetTimeOutCntInternal;
            end
            else begin
                timeOutCntReg <= timeOutCntReg - 1;
                // isTimeOutCntZeroReg <= isZero(timeOutCntReg);
                let {
                    isTimeOutCntHighPartZero, isTimeOutCntLowPartZero
                } = isZero4LargeBits(timeOutCntReg);
                isTimeOutCntHighPartZeroReg <= isTimeOutCntHighPartZero;
                isTimeOutCntLowPartZeroReg  <= isTimeOutCntLowPartZero;
            end
        end
    endrule

    rule handleNotifiedRetryAndTimeOut if (cntrl.isRTS);
        let maybeRetryReq = tagged Invalid;

        let hasNotifiedTimeOut = timeOutTriggerQ.notEmpty;
        // hasNotifiedRetry and shouldResetRetryCnt have priority over hasNotifiedTimeOut
        if (hasNotifiedTimeOut) begin
            timeOutTriggerQ.deq;
            let retryReq = dontCareValue;
            retryReq.retryReason = RETRY_REASON_TIMEOUT;
            maybeRetryReq = tagged Valid retryReq;
        end

        let hasRetryReq = retryNotificationQ.notEmpty;
        if (hasRetryReq) begin
            maybeRetryReq = retryNotificationQ.first;
            retryNotificationQ.deq;
        end

        if (hasNotifiedTimeOut || hasRetryReq) begin
            retryActionQ.enq(maybeRetryReq);
        end
    endrule

    rule handleRetryAction if (cntrl.isRTS);
        let maybeRetryReq = retryActionQ.first;
        retryActionQ.deq;

        let retryReqOrResetRetryCnt = isValid(maybeRetryReq);

        let updateRetryCnt = tagged Invalid;
        if (retryReqOrResetRetryCnt) begin
            immAssert(
                pendingWorkReqNotEmpty,
                "pendingWorkReqNotEmpty assertion @ mkRetryHandleSQ",
                $format(
                    "pendingWorkReqNotEmpty=", fshow(pendingWorkReqNotEmpty),
                    " should be true when retryReqOrResetRetryCnt=",
                    fshow(retryReqOrResetRetryCnt)
                )
            );

            let retryReq = unwrapMaybe(maybeRetryReq);
            if (retryReq.retryReason != RETRY_REASON_TIMEOUT) begin
                retryWorkReqIdReg <= retryReq.wrID;
                retryStartPsnReg  <= retryReq.retryStartPSN;

                if (retryReq.retryReason == RETRY_REASON_RNR) begin
                    immAssert(
                        isValid(retryReq.retryRnrTimer),
                        "retryRnrTimer assertion @ mkRetryHandleSQ",
                        $format(
                            "retryRnrTimer=", fshow(retryReq.retryRnrTimer),
                            " should be valid when retryReason=",
                            fshow(retryReq.retryReason)
                        )
                    );
                    retryRnrTimerReg <= unwrapMaybe(retryReq.retryRnrTimer);
                end
            end
            retryReasonReg <= retryReq.retryReason;

            updateRetryCnt = tagged Valid retryReq.retryReason;
            $display(
                "time=%0t: canonicalize", $time,
                ", retryReqOrResetRetryCnt=", fshow(retryReqOrResetRetryCnt)
            );
        end

        updateRetryCntQ.enq(updateRetryCnt);
    endrule

    rule handleRetryCntUpdate if (cntrl.isRTS && !pauseRetryHandleReg);
        let maybeRetryReason = updateRetryCntQ.first;
        updateRetryCntQ.deq;

        let hasRetryErr = retryCntrlStateReg[1] == RETRY_CNTRL_ST_RETRY_LIMIT_EXC;
        immAssert(
            !hasRetryErr,
            "hasRetryErr assertion @ mkRetryHandleSQ",
            $format(
                "hasRetryErr=", fshow(hasRetryErr),
                " should be false and retryCntrlStateReg[1]=",
                fshow(retryCntrlStateReg[1]),
                " should != RETRY_CNTRL_ST_RETRY_LIMIT_EXC",
                " when updateRetryCntQ.notEmpty=",
                fshow(updateRetryCntQ.notEmpty)
            )
        );

        if (maybeRetryReason matches tagged Valid .retryReason) begin
            pauseRetryHandleReg <= True;

            decRetryCntByReason(retryReason);

            if (retryCntExceedLimit(retryReason)) begin
                retryCntrlStateReg[1] <= RETRY_CNTRL_ST_RETRY_LIMIT_EXC;
                hasRetryErr = True;
            end
            else begin
                retryCntrlStateReg[1] <= RETRY_CNTRL_ST_INIT_RETRY;
            end
            prepareRetryRespQ.enq(tuple2(hasRetryErr, retryReason));
        end
        else begin
            resetRetryCntInternal;

            immAssert(
                pendingWorkReqNotEmpty,
                "pendingWorkReqNotEmpty assertion @ mkRetryHandleSQ",
                $format(
                    "pendingWorkReqNotEmpty=", fshow(pendingWorkReqNotEmpty),
                    " should be true when maybeRetryReason=",
                    fshow(maybeRetryReason)
                )
            );
        end
    endrule

    rule sendRetryResp if (cntrl.isRTS);
        let { hasRetryErr, retryReason } = prepareRetryRespQ.first;
        prepareRetryRespQ.deq;

        if (hasRetryErr) begin
            if (retryReason == RETRY_REASON_TIMEOUT) begin
                timeOutNotificationQ.enq(RETRY_HANDLER_TIMEOUT_ERR);
            end
            else begin
                retryRespQ.enq(RETRY_HANDLER_RETRY_LIMIT_EXC);
            end
            // $display("time=%0t: retry error occured", $time);
        end
        else begin
            if (retryReason == RETRY_REASON_TIMEOUT) begin
                timeOutNotificationQ.enq(RETRY_HANDLER_TIMEOUT_RETRY);
            end
            else begin
                retryRespQ.enq(RETRY_HANDLER_RECV_RETRY_REQ);
            end
            // $display(
            //     "time=%0t: retry request responded", $time, ", retryReason=", fshow(retryReason)
            // );
        end
        // $display("time=%0t: sendRetryResp", $time);
    endrule

    // Retry control FSM

    rule initRetry if (
        cntrl.isRTS && pauseRetryHandleReg &&
        retryCntrlStateReg[0] == RETRY_CNTRL_ST_INIT_RETRY
    );
        pauseRetryHandleReg <= False;
        retryHandleStateReg <= RETRY_HANDLE_ST_START_PRE_RETRY;
        retryCntrlStateReg[0] <= RETRY_CNTRL_ST_WAIT_RETRY_DONE;

        // $display("time=%0t: retry initiated", $time);
    endrule

    rule waitRetryFinish if (
        cntrl.isRTS &&
        retryCntrlStateReg[0] == RETRY_CNTRL_ST_WAIT_RETRY_DONE &&
        retryHandleStateReg == RETRY_HANDLE_ST_WAIT_RETRY_DONE
    );
        if (pendingWorkReqScanCntrl.isScanDone) begin
            retryCntrlStateReg[0] <= RETRY_CNTRL_ST_NOT_RETRY;

            // $display(
            //     "time=%0t: retry finished", $time,
            //     ", cntrl.isRTS=", fshow(cntrl.isRTS)
            // );
        end
    endrule

    rule stopScanQ if (
        cntrl.isERR ||
        (pauseRetryHandleReg && retryCntrlStateReg[0] == RETRY_CNTRL_ST_RETRY_LIMIT_EXC)
    );
        pendingWorkReqScanCntrl.scanStop;
        // updateRetryCntQ.clear;
        // $display("time=%0t: stop scanQ", $time);
    endrule

    // Retry handle FSM

    rule startPreRetry if (
        cntrl.isRTS && !pauseRetryHandleReg &&
        retryHandleStateReg == RETRY_HANDLE_ST_START_PRE_RETRY
    );
        immAssert(
            retryReasonReg != RETRY_REASON_NOT_RETRY,
            "retryReasonReg assertion @ mkRespHandleSQ",
            $format(
                "retryReasonReg=", fshow(retryReasonReg),
                " should not be RETRY_REASON_NOT_RETRY"
            )
        );

        if (retryReasonReg == RETRY_REASON_RNR) begin
            retryHandleStateReg <= RETRY_HANDLE_ST_RNR_CHECK;
        end
        else begin
            retryHandleStateReg <= RETRY_HANDLE_ST_CHECK_PARTIAL_RETRY_WR;
        end

        if (pendingWorkReqScanCntrl.isScanDone) begin
            pendingWorkReqScanCntrl.preScanStart;
            // $display(
            //     "time=%0t: pendingWorkReqScanCntrl.preScanStart", $time,
            //     " pendingWorkReqNotEmpty=", fshow(pendingWorkReqNotEmpty)
            // );
        end
        else begin
            pendingWorkReqScanCntrl.preScanRestart;
            // $display(
            //     "time=%0t: pendingWorkReqScanCntrl.preScanRestart", $time,
            //     " pendingWorkReqNotEmpty=", fshow(pendingWorkReqNotEmpty)
            // );
        end
        // $display(
        //     "time=%0t: startPreRetry", $time,
        //     ", retryHandleStateReg=", fshow(retryHandleStateReg),
        //     ", retryErr=", fshow(retryErr),
        //     ", retryReason=", fshow(retryReason)
        // );
    endrule

    rule rnrCheck if (
        cntrl.isRTS && !pauseRetryHandleReg &&
        retryHandleStateReg == RETRY_HANDLE_ST_RNR_CHECK
    );
        let rnrTimer = cntrl.getMinRnrTimer;
        rnrTimer = retryRnrTimerReg > rnrTimer ? retryRnrTimerReg : rnrTimer;
        rnrWaitCntReg <= fromInteger(getRnrTimeOutValue(rnrTimer));
        isRnrWaitCntZeroReg <= False;
        retryHandleStateReg <= RETRY_HANDLE_ST_RNR_WAIT;

        // $display(
        //     "time=%0t: rnrCheck", $time,
        //     ", retryReasonReg=", fshow(retryReasonReg),
        //     ", hasNotifiedRetryReg[0]=", fshow(hasNotifiedRetryReg[0])
        // );
    endrule

    rule rnrWait if (
        cntrl.isRTS && !pauseRetryHandleReg &&
        retryHandleStateReg == RETRY_HANDLE_ST_RNR_WAIT
    );
        if (isRnrWaitCntZeroReg) begin
            retryHandleStateReg <= RETRY_HANDLE_ST_CHECK_PARTIAL_RETRY_WR;
        end
        else begin
            rnrWaitCntReg <= rnrWaitCntReg - 1;
            isRnrWaitCntZeroReg <= isZero(rnrWaitCntReg);
        end

        // $display(
        //     "time=%0t: retry rnrWait", $time,
        //     ", rnrWaitCntReg=%h", rnrWaitCntReg
        // );
    endrule

    rule checkPartialRetry if (
        cntrl.isRTS && !pauseRetryHandleReg &&
        retryHandleStateReg == RETRY_HANDLE_ST_CHECK_PARTIAL_RETRY_WR
    );
        let firstRetryWR = pendingWorkReqScanCntrl.getHead;

        let startPSN = unwrapMaybe(firstRetryWR.startPSN);
        let endPSN   = unwrapMaybe(firstRetryWR.endPSN);
        let wrLen    = firstRetryWR.wr.len;
        let laddr    = firstRetryWR.wr.laddr;
        let raddr    = firstRetryWR.wr.raddr;

        let retryStartPSN = retryStartPsnReg;
        if (retryReasonReg == RETRY_REASON_TIMEOUT) begin
            retryStartPSN = startPSN;
        end
        else begin
            immAssert(
                retryWorkReqIdReg == firstRetryWR.wr.id,
                "retryWorkReqIdReg assertion @ mkRespHandleSQ",
                $format(
                    "retryWorkReqIdReg=%h should == firstRetryWR.wr.id=%h",
                    retryWorkReqIdReg, firstRetryWR.wr.id
                )
            );
        end

        psnDiffReg <= calcPsnDiff(retryStartPSN, startPSN);
        immAssert(
            retryStartPSN == startPSN ||
            retryStartPSN == endPSN   ||
            psnInRangeExclusive(retryStartPSN, startPSN, endPSN),
            "retryStartPSN assertion @ mkRetryHandleSQ",
            $format(
                "retryStartPSN=%h should between startPSN=%h and endPSN=%h inclusively",
                retryStartPSN, startPSN, endPSN
            )
        );

        retryHandleStateReg <= RETRY_HANDLE_ST_MODIFY_PARTIAL_RETRY_WR;
        $display("time=%0t:", $time, " check partial retry WR ID=%h", firstRetryWR.wr.id);
    endrule

    rule modifyPartialRetryWR if (
        cntrl.isRTS && !pauseRetryHandleReg &&
        retryHandleStateReg == RETRY_HANDLE_ST_MODIFY_PARTIAL_RETRY_WR
    );
        let firstRetryWR = pendingWorkReqScanCntrl.getHead;

        let wrLen = firstRetryWR.wr.len;
        let laddr = firstRetryWR.wr.laddr;
        let raddr = firstRetryWR.wr.raddr;
        let retryWorkReqLen       = lenSubtractPsnMultiplyPMTU(wrLen, psnDiffReg, cntrl.getPMTU);
        let retryWorkReqLocalAddr = addrAddPsnMultiplyPMTU(laddr, psnDiffReg, cntrl.getPMTU);
        let retryWorkReqRmtAddr   = addrAddPsnMultiplyPMTU(raddr, psnDiffReg, cntrl.getPMTU);
        if (retryReasonReg != RETRY_REASON_TIMEOUT) begin
            firstRetryWR.startPSN = tagged Valid retryStartPsnReg;
        end
        firstRetryWR.wr.len   = retryWorkReqLen;
        firstRetryWR.wr.laddr = retryWorkReqLocalAddr;
        firstRetryWR.wr.raddr = retryWorkReqRmtAddr;

        pendingWorkReqScanCntrl.modifyHead(firstRetryWR);
        retryHandleStateReg <= RETRY_HANDLE_ST_START_RETRY;

        // $display("time=%0t:", $time, " partial retry WR ID=%h", firstRetryWR.wr.id);
    endrule

    rule startRetry if (
        cntrl.isRTS && !pauseRetryHandleReg &&
        retryHandleStateReg == RETRY_HANDLE_ST_START_RETRY
    );
        pendingWorkReqScanCntrl.scanStart;
        retryHandleStateReg <= RETRY_HANDLE_ST_WAIT_RETRY_DONE;
    endrule

    rule waitRetryDone if (
        cntrl.isRTS && !pauseRetryHandleReg &&
        retryHandleStateReg == RETRY_HANDLE_ST_WAIT_RETRY_DONE
    );
        if (pendingWorkReqScanCntrl.isScanDone) begin
            retryHandleStateReg <= RETRY_HANDLE_ST_NOT_RETRY;

            // $display(
            //     "time=%0t: retry done", $time,
            //     ", cntrl.isRTS=", fshow(cntrl.isRTS)
            // );
        end
    endrule

    method Bool hasRetryErr() = retryErr;
    method Bool isRetryDone() = notRetrying;
    method Bool  isRetrying() = retryingWR;

    method Action resetRetryCntAndTimeOutBySQ(
        ResetRetryCntAndTimeOutReq resetReq
    ) if (cntrl.isRTS);
        resetReqQ.enq(resetReq);
    endmethod

    method ActionValue#(TimeOutNotification) notifyTimeOut2SQ();
        timeOutNotificationQ.deq;
        return timeOutNotificationQ.first;
    endmethod

    interface srvPort = toGPServer(retryReqQ, retryRespQ);
endmodule
