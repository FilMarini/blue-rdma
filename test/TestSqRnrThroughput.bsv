// Sustained-RNR SQ throughput test.
//
// PURPOSE: reproduce the "sticky half-throughput after backpressure clears"
// bug observed on hardware (Simple-10GbE-RUDP-KCU105-Example RoCEv2 datapath).
// On the bench the SQ completes RDMA-SENDs at full rate, then after a window of
// RNR-NAK backpressure (host recv queue transiently full) it latches at EXACTLY
// half the completion rate and never recovers until the source fully drains.
//
// VEHICLE: drive the full mkSQ (ReqGenSQ + RetryHandleSQ + RespHandleSQ +
// WorkCompGenSQ + the pending-WR scan-FIFO) -- the smallest unit that contains
// the complete dispatch<->response<->retry loop where re-dispatch throughput is
// observable. A continuous SEND-only WorkReq stream keeps the pending queue
// non-empty (continuous backlog), matching the hardware condition under which
// the latch persists.
//
// RESPONDER: reactive. Every request packet the SQ emits is observed, its BTH
// PSN extracted, and exactly one ACK fed back at that PSN -- an RNR-NAK while
// the cycle counter is inside [rnrStart, rnrStop), a normal ACK otherwise. This
// is PSN-consistent by construction and naturally covers retransmissions.
//
// MEASUREMENT: count WorkComps in a baseline window (before any RNR) and in a
// post-RNR steady-state window, and report completions/1000-cycles for each.
// PASS = post-RNR rate >= 0.8 * baseline rate. FAIL (bug present) = post-RNR
// rate ~= 0.5 * baseline (the stuck-half signature).

import ClientServer :: *;
import Connectable :: *;
import FIFOF :: *;
import GetPut :: *;
import PAClib :: *;
import Vector :: *;
import Cntrs :: *;

import Headers :: *;
import Controller :: *;
import DataTypes :: *;
import ExtractAndPrependPipeOut :: *;
import InputPktHandle :: *;
import PayloadConAndGen :: *;
import PrimUtils :: *;
import QueuePair :: *;
import ReqGenSQ :: *;
import RespHandleSQ :: *;
import RetryHandleSQ :: *;
import SimDma :: *;
import SimExtractRdmaHeaderPayload :: *;
import SimGenRdmaReqResp :: *;
import Settings :: *;
import Utils :: *;
import Utils4Test :: *;
import WorkCompGen :: *;

// Cycle windows (in clock cycles) for the RNR burst and the measurement spans.
// RNR window. Set RnrStartCycle == RnrStopCycle to DISABLE RNR entirely
// (pure-ACK harness self-check baseline).
typedef 4000  RnrStartCycle;   // let the baseline run clean first
typedef 12000 RnrStopCycle;    // sustained RNR window (~8000 cycles, several backoffs)
typedef 2500  BaselineSpan;    // baseline measurement window (pre-RNR)
typedef 4000  RecoverWaitCycle;// settle time after RNR stops before measuring
typedef 120000 SimEndCycle;    // hard stop (long, to see slow recovery vs stuck)
typedef 12     NumBuckets;     // 12 * 10000 = 120000 = SimEndCycle

// Pure-ACK harness self-check: NO RNR ever. Confirms the testbench sustains
// full SQ throughput end-to-end, so a "stuck" verdict in the RNR case is a real
// DUT behavior and not a harness artifact.
(* doc = "testcase" *)
module mkTestSqNoRnrBaselineCase(Empty);
    let _x <- mkSqRnrThroughputBody(False);
endmodule

(* doc = "testcase" *)
module mkTestSqRnrThroughputCase(Empty);
    let _x <- mkSqRnrThroughputBody(True);
endmodule

// Scan-FIFO replay-tail-drop coverage (mkScanFIFOF scanOutQ.clear bug).
//
// The mkTestSqRnrThroughput responder above is a BLIND echo-ACK: it ACKs every
// WR-end at that packet's own PSN. When the buggy SQ drops the last <=2 WRs of a
// retry replay and jumps ahead, the responder ACKs the higher-PSN WR-end, which
// the SQ treats as a CUMULATIVE ACK that silently absorbs the dropped WRs -- so
// the tail-drop is invisible and that test PASSES on buggy code.
//
// mkSqTailDropBody uses a STRICT in-order receiver instead: it ACKs only the
// in-order WR-end at the expected PSN, SEQ_ERR-NAKs a forward PSN gap (never
// cumulatively ACKs past a hole), and re-ACKs duplicates. Single-packet WRs make
// PSN index the WR directly (the hardware 4096B-SEND regime). A transient RNR
// burst kicks off one retry; on buggy FW the dropped replay tail leaves a gap the
// receiver SEQ_ERR-NAKs, forcing another truncated retry -> a self-perpetuating
// ~2x retransmit treadmill (steady-state TX/comp ~= 2.0). With the scanOutQ.clear
// fix the replay covers the full window, the gap closes, and TX/comp -> 1.0.
//
// VERDICT = steady-state TX/comp (req-pkts/work-comps in the last bucket):
// PASS <= 1.30, FAIL (bug present) ~= 2.0. The no-RNR case is the responder
// self-check (no retry -> no gap -> TX/comp == 1.0), proving the strict receiver
// does not itself manufacture the gap.
(* doc = "testcase" *)
module mkTestSqTailDropNoRnrCase(Empty);
    let _x <- mkSqTailDropBody(False);
endmodule

(* doc = "testcase" *)
module mkTestSqTailDropCase(Empty);
    let _x <- mkSqTailDropBody(True);
endmodule

module mkSqRnrThroughputBody#(Bool enableRnr)(Empty);
    // SEND-only, MULTI-packet WRs: payload spans several PMTUs so each WR has a
    // multi-PSN range (startPSN..endPSN). This exercises the go-back-N coalesce /
    // nextPSN window + isOnlyReqPkt/remainingPktNum reload path in ReqGenSQ/
    // RespHandleSQ that single-packet WRs bypass entirely -- the suspected home of
    // the one-behind retransmit latch (HW: TX/comp=2.0 persistent after RNR).
    let minDmaLength = 512;   // > PMTU (256) => >= 2 packets/WR
    let maxDmaLength = 1024;  // up to ~4 packets/WR
    let qpType = IBV_QPT_RC;
    let pmtu   = IBV_MTU_256;

    // ---- Controller driven to RTS with INFINITE RNR retry ----
    // The shared mkSimCntrl hard-codes rnrRetry = DEFAULT_RETRY_NUM (3), which
    // makes a long RNR burst exhaust the retry budget and ERROR the QP -- that
    // masks the sticky-half bug with a permanent stall. Hardware runs
    // rnrRetry = 7 = INFINITE_RETRY, so drive the QP to RTS locally with
    // infinite RNR + data retry to match the bench.
    let cntrl <- mkCntrlQP;
    let cntrlStatus = cntrl.contextSQ.statusSQ;
    let qpn = getDefaultQPN;
    let qpInitAttr = QpInitAttr { qpType: qpType, sqSigAll: False };

    function AttrQP infRetryQpAttr();
        return AttrQP {
            qpState          : dontCareValue,
            curQpState       : dontCareValue,
            pmtu             : pmtu,
            qkey             : fromInteger(valueOf(DEFAULT_QKEY)),
            rqPSN            : 0,
            sqPSN            : 0,
            dqpn             : getDefaultQPN,
            qpAccessFlags    : enum2Flag(IBV_ACCESS_REMOTE_WRITE) |
                               enum2Flag(IBV_ACCESS_REMOTE_READ) |
                               enum2Flag(IBV_ACCESS_REMOTE_ATOMIC),
            cap              : QpCapacity {
                maxSendWR    : fromInteger(valueOf(MAX_QP_WR)),
                maxRecvWR    : fromInteger(valueOf(MAX_QP_WR)),
                maxSendSGE   : fromInteger(valueOf(MAX_SEND_SGE)),
                maxRecvSGE   : fromInteger(valueOf(MAX_RECV_SGE)),
                maxInlineData: fromInteger(valueOf(MAX_INLINE_DATA))
            },
            pkeyIndex        : fromInteger(valueOf(DEFAULT_PKEY)),
            sqDraining       : False,
            maxReadAtomic    : fromInteger(valueOf(MAX_QP_RD_ATOM)),
            maxDestReadAtomic: fromInteger(valueOf(MAX_QP_DST_RD_ATOM)),
            minRnrTimer      : 1,
            timeout          : 0,  // 0 = infinite response timeout (no timeout retries)
            retryCnt         : fromInteger(valueOf(INFINITE_RETRY)),
            rnrRetry         : fromInteger(valueOf(INFINITE_RETRY))
        };
    endfunction

    Reg#(Bit#(3)) qpSetupStateReg <- mkReg(0);
    rule qpCreate if (qpSetupStateReg == 0 && cntrlStatus.comm.isReset);
        cntrl.srvPort.request.put(ReqQP {
            qpReqType: REQ_QP_CREATE, pdHandler: dontCareValue, qpn: qpn,
            qpAttrMask: dontCareValue, qpAttr: dontCareValue, qpInitAttr: qpInitAttr });
        qpSetupStateReg <= 1;
    endrule
    rule qpInit if (qpSetupStateReg == 1);
        let resp <- cntrl.srvPort.response.get;
        let a = infRetryQpAttr; a.qpState = IBV_QPS_INIT;
        cntrl.srvPort.request.put(ReqQP {
            qpReqType: REQ_QP_MODIFY, pdHandler: dontCareValue, qpn: qpn,
            qpAttrMask: getReset2InitRequiredAttr, qpAttr: a, qpInitAttr: qpInitAttr });
        qpSetupStateReg <= 2;
    endrule
    rule qpRtr if (qpSetupStateReg == 2);
        let resp <- cntrl.srvPort.response.get;
        let a = infRetryQpAttr; a.qpState = IBV_QPS_RTR;
        cntrl.srvPort.request.put(ReqQP {
            qpReqType: REQ_QP_MODIFY, pdHandler: dontCareValue, qpn: qpn,
            qpAttrMask: getInit2RtrRequiredAttr, qpAttr: a, qpInitAttr: qpInitAttr });
        qpSetupStateReg <= 3;
    endrule
    rule qpRts if (qpSetupStateReg == 3);
        let resp <- cntrl.srvPort.response.get;
        let a = infRetryQpAttr; a.qpState = IBV_QPS_RTS;
        cntrl.srvPort.request.put(ReqQP {
            qpReqType: REQ_QP_MODIFY, pdHandler: dontCareValue, qpn: qpn,
            qpAttrMask: getRtr2RtsRequiredAttr, qpAttr: a, qpInitAttr: qpInitAttr });
        qpSetupStateReg <= 4;
    endrule
    rule qpRtsResp if (qpSetupStateReg == 4);
        let resp <- cntrl.srvPort.response.get;
        qpSetupStateReg <= 5;  // QP now in RTS
    endrule

    // ---- Continuous WorkReq source (raw WorkReq into mkSQ) ----
    Vector#(1, PipeOut#(WorkReq)) sendWorkReqPipeOutVec <- mkRandomSendWorkReq(
        minDmaLength, maxDmaLength
    );
    let workReqPipeIn = sendWorkReqPipeOutVec[0];

    // ---- Payload generator + DMA model for the SQ request path ----
    let simDmaReadSrv <- mkSimDmaReadSrv;
    let dmaReadCntrl  <- mkDmaReadCntrl(cntrlStatus, simDmaReadSrv);
    let payloadGenerator <- mkPayloadGenerator(cntrlStatus, dmaReadCntrl);

    // ---- Response path plumbing ----
    // The reactive responder builds ACK headers into respHeaderQ; they are
    // turned into a response DataStream and then into RdmaPktMetaData+payload
    // that mkSQ consumes as respPktPipeOut.
    FIFOF#(HeaderRDMA) respHeaderQ <- mkFIFOF;
    let respHeaderDataStreamAndMeta <- mkHeader2DataStream(
        cntrlStatus.comm.isReset, toPipeOut(respHeaderQ)
    );
    mkSink(respHeaderDataStreamAndMeta.headerMetaData);
    let respPktMetaDataAndPayload <- mkSimExtractNormalHeaderPayload(
        respHeaderDataStreamAndMeta.headerDataStream
    );

    // ---- DUT: the full Send Queue ----
    let dut <- mkSQ(
        cntrl.contextSQ,
        payloadGenerator,
        workReqPipeIn,
        respPktMetaDataAndPayload
    );

    // ---- Observe emitted request packets to drive the reactive responder ----
    let reqHeaderAndPayload <- mkExtractHeaderFromRdmaPktPipeOut(
        dut.rdmaReqDataStreamPipeOut
    );
    let reqHeaderPipeOut <- mkDataStream2Header(
        reqHeaderAndPayload.headerAndMetaData.headerDataStream,
        reqHeaderAndPayload.headerAndMetaData.headerMetaData
    );
    // Drain the request payload (we only need the headers to generate ACKs).
    let sinkReqPayload <- mkSink(reqHeaderAndPayload.payload);

    // ---- Free-running cycle counter (drives the RNR window + measurement) ----
    Reg#(Bit#(32)) cycleReg <- mkReg(0);
    (* no_implicit_conditions, fire_when_enabled *)
    rule tick;
        cycleReg <= cycleReg + 1;
        if (cycleReg == fromInteger(valueOf(SimEndCycle))) begin
            $finish(0);
        end
    endrule

    let inRnrWindow = enableRnr &&
                      (cycleReg >= fromInteger(valueOf(RnrStartCycle))) &&
                      (cycleReg <  fromInteger(valueOf(RnrStopCycle)));

    // Request-packet emission instrumentation (distinguishes a DUT throughput
    // latch from a testbench responder-handshake artifact: if request packets
    // keep flowing but WCs stop, the latch is in the DUT response/retry path).
    Count#(Bit#(32)) reqPktSeenCnt <- mkCount(0);
    Vector#(NumBuckets, Count#(Bit#(32))) reqBucket <- replicateM(mkCount(0));

    // ---- Reactive responder: one ACK per emitted request packet ----
    // RNR-NAK while inside the window (echo BTH PSN, AETH RNR), else normal ACK.
    // The window is INTERMITTENT: NAK only a fraction (rnrNakMod-1)/rnrNakMod of
    // packets, letting the rest complete -- this models heavy-but-partial host
    // backpressure (host slightly behind), the actual hardware regime, rather
    // than a 100%-NAK total stall.
    Reg#(Bit#(32)) respWrCntReg <- mkReg(0);
    Integer rnrNakMod = 4;  // during the window, NAK 3 of every 4 WHOLE WRs
    rule genAckForReq;
        let rdmaHeader = reqHeaderPipeOut.first;
        reqHeaderPipeOut.deq;

        let bthIn = extractBTH(rdmaHeader.headerData);
        let { transTypeIn, rdmaOpCodeIn } =
            extractTranTypeAndRdmaOpCode(rdmaHeader.headerData);

        // Only the LAST (or ONLY) packet of a WR triggers a whole-WR response, at
        // its endPSN -- a clean cumulative ACK / RNR-NAK for the WR. Intermediate
        // packets of a multi-packet SEND get no response (drained, no enq).
        let isWrEnd = isLastOrOnlyRdmaOpCode(rdmaOpCodeIn);
        if (isWrEnd) begin
            respWrCntReg <= respWrCntReg + 1;
        end
        let doNak = isWrEnd && inRnrWindow &&
                    ((respWrCntReg % fromInteger(rnrNakMod)) != 0);

        let maybeTrans = qpType2TransType(cntrlStatus.getTypeQP);
        let transType  = unwrapMaybe(maybeTrans);

        let bth = BTH {
            trans    : transType,
            opcode   : ACKNOWLEDGE,
            solicited: False,
            migReq   : unpack(0),
            padCnt   : 0,
            tver     : unpack(0),
            pkey     : cntrlStatus.comm.getPKEY,
            fecn     : unpack(0),
            becn     : unpack(0),
            resv6    : unpack(0),
            dqpn     : cntrlStatus.comm.getSQPN,
            ackReq   : False,
            resv7    : unpack(0),
            psn      : bthIn.psn   // endPSN of the WR (last packet)
        };
        let aeth = doNak ?
            AETH {
                rsvd : unpack(0),
                code : AETH_CODE_RNR,
                value: cntrlStatus.comm.getMinRnrTimer,
                msn  : dontCareValue
            } :
            AETH {
                rsvd : unpack(0),
                code : AETH_CODE_ACK,
                value: pack(AETH_ACK_VALUE_INVALID_CREDIT_CNT),
                msn  : dontCareValue
            };
        // Respond ONLY to whole-WR ends. reqBucket counts WR transmissions (one per
        // last-packet seen) so reqBucket vs wcBucket == TX/comp at WR granularity,
        // matching the hardware DmaReadCount-vs-SuccessCounter measurement.
        if (isWrEnd) begin
            let respHeader = genHeaderRDMA(
                zeroExtendLSB({ pack(bth), pack(aeth) }),
                fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(AETH_BYTE_WIDTH)),
                False
            );
            respHeaderQ.enq(respHeader);
            reqPktSeenCnt.incr(1);
            let bidx = cycleReg / fromInteger(10000);
            for (Integer i = 0; i < valueOf(NumBuckets); i = i + 1) begin
                if (bidx == fromInteger(i)) reqBucket[i].incr(1);
            end
        end
    endrule

    // ---- Measure WorkComp throughput as a trajectory ----
    // Bucket completions into consecutive 5000-cycle bins so the time-course is
    // visible: baseline (full) -> RNR window (low) -> post-RNR steady state.
    let workCompPipeOut = dut.workCompSQ.workCompPipeOut;

    Integer bucketSpan = 10000;       // NumBuckets * bucketSpan = SimEndCycle
    Vector#(NumBuckets, Count#(Bit#(32))) wcBucket <- replicateM(mkCount(0));
    Reg#(Bit#(32)) totalWcReg  <- mkReg(0);
    Reg#(Bit#(32)) errWcReg    <- mkReg(0);  // non-SUCCESS WCs (retry-exhaust / err)

    rule countWorkComp;
        let wc = workCompPipeOut.first;
        workCompPipeOut.deq;
        totalWcReg <= totalWcReg + 1;
        if (wc.status != IBV_WC_SUCCESS) begin
            errWcReg <= errWcReg + 1;
        end

        let idx = cycleReg / fromInteger(bucketSpan);
        for (Integer i = 0; i < valueOf(NumBuckets); i = i + 1) begin
            if (idx == fromInteger(i)) begin
                wcBucket[i].incr(1);
            end
        end
    endrule

    // ---- Report + verdict near the end of the sim ----
    Reg#(Bool) reportedReg <- mkReg(False);
    rule report if (!reportedReg && cycleReg == (fromInteger(valueOf(SimEndCycle)) - 1));
        reportedReg <= True;

        $display("=========================================================");
        $display("SQ RNR THROUGHPUT TEST  (RNR window cycles [%0d, %0d))",
                 valueOf(RnrStartCycle), valueOf(RnrStopCycle));
        $display("  total WorkComps : %0d  (non-SUCCESS WCs: %0d)", totalWcReg, errWcReg);
        $display("  total req pkts seen : %0d", reqPktSeenCnt);
        $display("  per %0d-cycle bucket (reqPkts / workComps):", bucketSpan);
        for (Integer i = 0; i < valueOf(NumBuckets); i = i + 1) begin
            $display("    bucket %0d  [cyc %0d..%0d) : reqPkt=%0d  WC=%0d",
                     i, i*bucketSpan, (i+1)*bucketSpan, reqBucket[i], wcBucket[i]);
        end

        // baseline = bucket 0 (pre-RNR, full rate); steadyState = last bucket
        // (long after RNR stopped). Bug = steadyState ~= 0.5 * baseline (or less)
        // with NO recovery. PASS = steadyState >= 0.8 * baseline.
        let baseline = wcBucket[0];
        let steady   = wcBucket[valueOf(NumBuckets)-1];
        let pct = (baseline == 0) ? 0 : (steady * 100) / baseline;
        $display("  baseline(bucket0)=%0d  steadyState(last)=%0d  -> %0d%% of baseline",
                 baseline, steady, pct);
        if (pct >= 80) begin
            $display("  VERDICT : PASS (recovered to >=80%% of baseline)");
        end
        else begin
            $display("  VERDICT : FAIL -- STUCK (steady state %0d%% of baseline, no recovery)", pct);
        end
        $display("=========================================================");
        // Fail loudly so CI (greps for "Error"/"ImmAssert") catches a regression
        // of the nested-RNR retry deadlock this test guards.
        immAssert(
            pct >= 80,
            "SQ RNR throughput recovery assertion @ mkTestSqRnrThroughput",
            $format(
                "post-RNR steady-state throughput=%0d%% of baseline should be >=80%%",
                pct, " (nested-RNR retry-FSM deadlock regression)"
            )
        );
        $finish(0);
    endrule
endmodule

// ---------------------------------------------------------------------------
// Scan-FIFO replay-tail-drop regression (strict in-order receiver).
// ---------------------------------------------------------------------------
module mkSqTailDropBody#(Bool enableRnr)(Empty);
    // SINGLE-packet WRs: payload <= PMTU so each WR is exactly one packet = one
    // PSN. PSN then indexes the WR directly (the hardware 4096B-SEND / PMTU-4096
    // regime), making the strict in-order receiver's gap detection unambiguous.
    let dmaLength = 256;          // == PMTU => exactly 1 packet/WR
    let qpType = IBV_QPT_RC;
    let pmtu   = IBV_MTU_256;

    // ---- Controller -> RTS with INFINITE RNR + data retry (matches hardware) ----
    let cntrl <- mkCntrlQP;
    let cntrlStatus = cntrl.contextSQ.statusSQ;
    let qpn = getDefaultQPN;
    let qpInitAttr = QpInitAttr { qpType: qpType, sqSigAll: False };

    function AttrQP infRetryQpAttr();
        return AttrQP {
            qpState          : dontCareValue,
            curQpState       : dontCareValue,
            pmtu             : pmtu,
            qkey             : fromInteger(valueOf(DEFAULT_QKEY)),
            rqPSN            : 0,
            sqPSN            : 0,
            dqpn             : getDefaultQPN,
            qpAccessFlags    : enum2Flag(IBV_ACCESS_REMOTE_WRITE) |
                               enum2Flag(IBV_ACCESS_REMOTE_READ) |
                               enum2Flag(IBV_ACCESS_REMOTE_ATOMIC),
            cap              : QpCapacity {
                maxSendWR    : fromInteger(valueOf(MAX_QP_WR)),
                maxRecvWR    : fromInteger(valueOf(MAX_QP_WR)),
                maxSendSGE   : fromInteger(valueOf(MAX_SEND_SGE)),
                maxRecvSGE   : fromInteger(valueOf(MAX_RECV_SGE)),
                maxInlineData: fromInteger(valueOf(MAX_INLINE_DATA))
            },
            pkeyIndex        : fromInteger(valueOf(DEFAULT_PKEY)),
            sqDraining       : False,
            maxReadAtomic    : fromInteger(valueOf(MAX_QP_RD_ATOM)),
            maxDestReadAtomic: fromInteger(valueOf(MAX_QP_DST_RD_ATOM)),
            minRnrTimer      : 1,
            timeout          : 0,
            retryCnt         : fromInteger(valueOf(INFINITE_RETRY)),
            rnrRetry         : fromInteger(valueOf(INFINITE_RETRY))
        };
    endfunction

    Reg#(Bit#(3)) qpSetupStateReg <- mkReg(0);
    rule qpCreate if (qpSetupStateReg == 0 && cntrlStatus.comm.isReset);
        cntrl.srvPort.request.put(ReqQP {
            qpReqType: REQ_QP_CREATE, pdHandler: dontCareValue, qpn: qpn,
            qpAttrMask: dontCareValue, qpAttr: dontCareValue, qpInitAttr: qpInitAttr });
        qpSetupStateReg <= 1;
    endrule
    rule qpInit if (qpSetupStateReg == 1);
        let resp <- cntrl.srvPort.response.get;
        let a = infRetryQpAttr; a.qpState = IBV_QPS_INIT;
        cntrl.srvPort.request.put(ReqQP {
            qpReqType: REQ_QP_MODIFY, pdHandler: dontCareValue, qpn: qpn,
            qpAttrMask: getReset2InitRequiredAttr, qpAttr: a, qpInitAttr: qpInitAttr });
        qpSetupStateReg <= 2;
    endrule
    rule qpRtr if (qpSetupStateReg == 2);
        let resp <- cntrl.srvPort.response.get;
        let a = infRetryQpAttr; a.qpState = IBV_QPS_RTR;
        cntrl.srvPort.request.put(ReqQP {
            qpReqType: REQ_QP_MODIFY, pdHandler: dontCareValue, qpn: qpn,
            qpAttrMask: getInit2RtrRequiredAttr, qpAttr: a, qpInitAttr: qpInitAttr });
        qpSetupStateReg <= 3;
    endrule
    rule qpRts if (qpSetupStateReg == 3);
        let resp <- cntrl.srvPort.response.get;
        let a = infRetryQpAttr; a.qpState = IBV_QPS_RTS;
        cntrl.srvPort.request.put(ReqQP {
            qpReqType: REQ_QP_MODIFY, pdHandler: dontCareValue, qpn: qpn,
            qpAttrMask: getRtr2RtsRequiredAttr, qpAttr: a, qpInitAttr: qpInitAttr });
        qpSetupStateReg <= 4;
    endrule
    rule qpRtsResp if (qpSetupStateReg == 4);
        let resp <- cntrl.srvPort.response.get;
        qpSetupStateReg <= 5;
    endrule

    // ---- Continuous SEND-only WorkReq source (fixed single-packet length) ----
    Vector#(1, PipeOut#(WorkReq)) sendWorkReqPipeOutVec <- mkRandomSendWorkReq(
        dmaLength, dmaLength
    );
    let workReqPipeIn = sendWorkReqPipeOutVec[0];

    let simDmaReadSrv <- mkSimDmaReadSrv;
    let dmaReadCntrl  <- mkDmaReadCntrl(cntrlStatus, simDmaReadSrv);
    let payloadGenerator <- mkPayloadGenerator(cntrlStatus, dmaReadCntrl);

    FIFOF#(HeaderRDMA) respHeaderQ <- mkFIFOF;
    let respHeaderDataStreamAndMeta <- mkHeader2DataStream(
        cntrlStatus.comm.isReset, toPipeOut(respHeaderQ)
    );
    mkSink(respHeaderDataStreamAndMeta.headerMetaData);
    let respPktMetaDataAndPayload <- mkSimExtractNormalHeaderPayload(
        respHeaderDataStreamAndMeta.headerDataStream
    );

    let dut <- mkSQ(
        cntrl.contextSQ, payloadGenerator, workReqPipeIn, respPktMetaDataAndPayload
    );

    let reqHeaderAndPayload <- mkExtractHeaderFromRdmaPktPipeOut(
        dut.rdmaReqDataStreamPipeOut
    );
    let reqHeaderPipeOut <- mkDataStream2Header(
        reqHeaderAndPayload.headerAndMetaData.headerDataStream,
        reqHeaderAndPayload.headerAndMetaData.headerMetaData
    );
    let sinkReqPayload <- mkSink(reqHeaderAndPayload.payload);

    Reg#(Bit#(32)) cycleReg <- mkReg(0);
    (* no_implicit_conditions, fire_when_enabled *)
    rule tick;
        cycleReg <= cycleReg + 1;
        if (cycleReg == fromInteger(valueOf(SimEndCycle))) $finish(0);
    endrule

    // Transient RNR burst: NAK whole-WR ends inside the window so the recv buffer
    // is "dry" briefly, then clears -- the backpressure-then-recover trigger.
    let inRnrWindow = enableRnr &&
                      (cycleReg >= fromInteger(valueOf(RnrStartCycle))) &&
                      (cycleReg <  fromInteger(valueOf(RnrStopCycle)));

    // ---- STRICT in-order RC receiver ----
    // ePsnReg = next in-order PSN expected. nakArmedReg coalesces: one SEQ_ERR-NAK
    // per gap episode, suppressed until the in-order packet arrives (a real RC RQ).
    Reg#(PSN)  ePsnReg     <- mkReg(0);
    Reg#(Bool) nakArmedReg <- mkReg(False);

    Count#(Bit#(32)) reqPktSeenCnt <- mkCount(0);
    Vector#(NumBuckets, Count#(Bit#(32))) reqBucket <- replicateM(mkCount(0));

    rule genAckForReq;
        let rdmaHeader = reqHeaderPipeOut.first;
        reqHeaderPipeOut.deq;

        let bthIn = extractBTH(rdmaHeader.headerData);
        let { transTypeIn, rdmaOpCodeIn } =
            extractTranTypeAndRdmaOpCode(rdmaHeader.headerData);
        let isWrEnd = isLastOrOnlyRdmaOpCode(rdmaOpCodeIn);

        let maybeTrans = qpType2TransType(cntrlStatus.getTypeQP);
        let transType  = unwrapMaybe(maybeTrans);

        // Decide the response for this WR-end against the strict expected PSN.
        // sendResp/respPsn/respCode default to "no response" (intermediate pkt).
        Bool      sendResp = False;
        PSN       respPsn  = bthIn.psn;
        AethCode  respCode = AETH_CODE_ACK;
        AethValue respVal  = pack(AETH_ACK_VALUE_INVALID_CREDIT_CNT);

        if (isWrEnd) begin
            reqPktSeenCnt.incr(1);
            let bidx = cycleReg / fromInteger(10000);
            for (Integer i = 0; i < valueOf(NumBuckets); i = i + 1) begin
                if (bidx == fromInteger(i)) reqBucket[i].incr(1);
            end

            if (bthIn.psn == ePsnReg) begin
                // In order. RNR-NAK during the window (no advance); else ACK + advance.
                nakArmedReg <= False;
                if (inRnrWindow) begin
                    sendResp = True; respCode = AETH_CODE_RNR;
                    respVal  = cntrlStatus.comm.getMinRnrTimer;
                end
                else begin
                    sendResp = True; respCode = AETH_CODE_ACK; respPsn = bthIn.psn;
                    ePsnReg <= ePsnReg + 1;
                end
            end
            else begin
                // Out of order. ahead = psn - ePSN (mod 2^24): MSB clear & nonzero =>
                // forward gap; MSB set => stale duplicate behind ePSN. (Single-packet
                // WRs advance ePSN by 1, so the half-space split is unambiguous here.)
                PSN ahead = bthIn.psn - ePsnReg;
                Bool isForwardGap = (msb(ahead) == 0);
                if (isForwardGap) begin
                    // FORWARD GAP -> one coalesced SEQ_ERR-NAK at ePSN, then suppress
                    // until the in-order packet arrives (never cumulatively ACK past
                    // a hole -- that is what lets the buggy tail-drop hide).
                    if (!nakArmedReg) begin
                        nakArmedReg <= True;
                        sendResp = True; respPsn = ePsnReg;
                        respCode = AETH_CODE_NAK; respVal = zeroExtend(pack(AETH_NAK_SEQ_ERR));
                    end
                end
                else begin
                    // DUPLICATE / old retransmit -> re-ACK the cumulative high-water.
                    sendResp = True; respPsn = (ePsnReg - 1);
                    respCode = AETH_CODE_ACK;
                end
            end
        end

        if (sendResp) begin
            let bth = BTH {
                trans : transType, opcode: ACKNOWLEDGE, solicited: False,
                migReq: unpack(0), padCnt: 0, tver: unpack(0),
                pkey  : cntrlStatus.comm.getPKEY, fecn: unpack(0), becn: unpack(0),
                resv6 : unpack(0), dqpn: cntrlStatus.comm.getSQPN, ackReq: False,
                resv7 : unpack(0), psn: respPsn
            };
            let aeth = AETH {
                rsvd: unpack(0), code: respCode, value: respVal, msn: dontCareValue
            };
            let respHeader = genHeaderRDMA(
                zeroExtendLSB({ pack(bth), pack(aeth) }),
                fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(AETH_BYTE_WIDTH)),
                False
            );
            respHeaderQ.enq(respHeader);
        end
    endrule

    let workCompPipeOut = dut.workCompSQ.workCompPipeOut;
    Integer bucketSpan = 10000;
    Vector#(NumBuckets, Count#(Bit#(32))) wcBucket <- replicateM(mkCount(0));
    Reg#(Bit#(32)) totalWcReg <- mkReg(0);
    Reg#(Bit#(32)) errWcReg   <- mkReg(0);

    rule countWorkComp;
        let wc = workCompPipeOut.first;
        workCompPipeOut.deq;
        totalWcReg <= totalWcReg + 1;
        if (wc.status != IBV_WC_SUCCESS) errWcReg <= errWcReg + 1;
        let idx = cycleReg / fromInteger(bucketSpan);
        for (Integer i = 0; i < valueOf(NumBuckets); i = i + 1) begin
            if (idx == fromInteger(i)) wcBucket[i].incr(1);
        end
    endrule

    Reg#(Bool) reportedReg <- mkReg(False);
    rule report if (!reportedReg && cycleReg == (fromInteger(valueOf(SimEndCycle)) - 1));
        reportedReg <= True;

        $display("=========================================================");
        $display("SQ TAIL-DROP TEST  (strict in-order receiver, RNR window [%0d,%0d), enableRnr=",
                 valueOf(RnrStartCycle), valueOf(RnrStopCycle), fshow(enableRnr), ")");
        $display("  total WorkComps : %0d  (non-SUCCESS WCs: %0d)", totalWcReg, errWcReg);
        $display("  total req WR-ends seen : %0d", reqPktSeenCnt);
        $display("  per %0d-cycle bucket (reqPkts / workComps):", bucketSpan);
        for (Integer i = 0; i < valueOf(NumBuckets); i = i + 1) begin
            $display("    bucket %0d  [cyc %0d..%0d) : reqPkt=%0d  WC=%0d",
                     i, i*bucketSpan, (i+1)*bucketSpan, reqBucket[i], wcBucket[i]);
        end

        // Steady-state TX/comp = reqPkts/workComps in the last bucket (long after
        // the RNR window). Healthy go-back-N -> ~1.0; the scanOutQ.clear tail-drop
        // treadmill -> ~2.0. Report as a percentage (100 == 1.00x).
        let reqLast = reqBucket[valueOf(NumBuckets)-1];
        let wcLast  = wcBucket[valueOf(NumBuckets)-1];
        let txPerCompPct = (wcLast == 0) ? 0 : (reqLast * 100) / wcLast;
        $display("  steady-state(last bucket) reqPkts=%0d workComps=%0d -> TX/comp=%0d%%",
                 reqLast, wcLast, txPerCompPct);

        // PASS <= 130% (1.30x): allows the bounded record-lag catch-up transient but
        // rejects the ~2x perpetual treadmill. The no-RNR self-check must be ~100%.
        if (txPerCompPct <= 130) begin
            $display("  VERDICT : PASS (steady-state TX/comp=%0d%% <= 130%%)", txPerCompPct);
        end
        else begin
            $display("  VERDICT : FAIL -- TAIL-DROP TREADMILL (TX/comp=%0d%%, expect ~200%%)", txPerCompPct);
        end
        $display("=========================================================");
        immAssert(
            txPerCompPct <= 130,
            "SQ tail-drop TX/comp assertion @ mkTestSqTailDrop",
            $format(
                "steady-state TX/comp=%0d%% should be <=130%%", txPerCompPct,
                " (mkScanFIFOF scanOutQ.clear replay-tail-drop regression)"
            )
        );
        $finish(0);
    endrule
endmodule
