import Connectable :: *;
import FIFOF :: *;
import GetPut :: *;
import PAClib :: *;
import Vector :: *;
import DReg :: *;

import Arbitration :: *;
import Controller :: *;
import DataTypes :: *;
import ExtractAndPrependPipeOut :: *;
import Headers :: *;
import InputPktHandle :: *;
import MetaData :: *;
import PrimUtils :: *;
import QueuePair :: *;
import Settings :: *;
import Utils :: *;
import PortConversion :: *;
import ClientServer :: *;


// TODO: check QP state when dispatching WR and RR,
// and discard WR and RR when QP in abnormal state
module mkWorkReqAndRecvReqDispatcher#(
    PipeOut#(WorkReq) workReqPipeIn
)(Vector#(MAX_QP, PipeOut#(WorkReq)));
    Vector#(MAX_QP, FIFOF#(WorkReq)) workReqOutVec <- replicateM(mkFIFOF);

    rule dispatchWorkReq;
        let wr = workReqPipeIn.first;
        workReqPipeIn.deq;

        let qpIndex = getIndexQP(wr.sqpn);
        workReqOutVec[qpIndex].enq(wr);
    endrule

    return map(toPipeOut, workReqOutVec);

endmodule

interface TransportLayer;
    interface Put#(WorkReq) workReqInput;
    interface Put#(DataStream) rdmaDataStreamInput;
    interface DataStreamPipeOut rdmaDataStreamPipeOut;
    interface PipeOut#(WorkComp) workCompPipeOutSQ;
    interface MetaDataSrv srvPortMetaData;
    interface DmaReadClt  dmaReadClt;
    (* always_ready *)
    method Vector#(MAX_QP, Bool) cnpReceived;
endinterface


(* synthesize *)
module mkTransportLayer(TransportLayer) provisos(
    NumAlias#(TDiv#(MAX_QP, MAX_PD), qpPerPdNum),
    Add#(TMul#(qpPerPdNum, MAX_PD), 0, MAX_QP), // MAX_QP can be divided by MAX_PD
    NumAlias#(TDiv#(MAX_MR, MAX_PD), mrPerPdNum),
    Add#(TMul#(mrPerPdNum, MAX_PD), 0, MAX_MR) // MAX_MR can be divided by MAX_PD
);
    FIFOF#(DataStream) inputDataStreamQ <- mkFIFOF;
    let rdmaReqRespPipeIn = toPipeOut(inputDataStreamQ);

    FIFOF#(WorkReq) inputWorkReqQ <- mkFIFOF;

    let pdMetaData  <- mkMetaDataPDs;
    let qpMetaData  <- mkMetaDataQPs;
    let metaDataSrv <- mkMetaDataSrv(pdMetaData, qpMetaData);

    let workReqPipeOutVec <- mkWorkReqAndRecvReqDispatcher(
        toPipeOut(inputWorkReqQ)
    );

    let headerAndMetaDataAndPayloadPipeOut <- mkExtractHeaderFromRdmaPktPipeOut(
        rdmaReqRespPipeIn
    );
    let pktMetaDataAndPayloadPipeOutVec <- mkInputRdmaPktBufAndHeaderValidation(
        headerAndMetaDataAndPayloadPipeOut, qpMetaData
    );

    Vector#(MAX_QP, PipeOut#(WorkComp)) qpSendWorkCompPipeOutVec = newVector;

    Vector#(TMul#(1, MAX_QP), DataStreamPipeOut) qpDataStreamPipeOutVec = newVector;
    Vector#(TMul#(1, MAX_QP), DmaReadClt)        dmaReadCltVec          = newVector;

    // Per-QP CNP pulse signals using mkDReg.
    // mkDReg(False) automatically resets to False every cycle unless written,
    // so a single rule writing True is sufficient — no separate clear rule needed,
    // and no scheduling conflict can occur.
    Vector#(MAX_QP, Reg#(Bool)) cnpPulseVec <- replicateM(mkDReg(False));

    for (Integer idx = 0; idx < valueOf(MAX_QP); idx = idx + 1) begin
        IndexQP qpIndex = fromInteger(idx);
        let qp = qpMetaData.getQueuePairByIndexQP(qpIndex);

        mkConnection(toGet(workReqPipeOutVec[idx]), qp.workReqIn);
        mkConnection(
            pktMetaDataAndPayloadPipeOutVec[idx].respPktPipeOut,
            qp.respPktPipeIn
        );

        qpSendWorkCompPipeOutVec[idx] = qp.workCompPipeOutSQ;
        qpDataStreamPipeOutVec[idx]   = qp.rdmaReqPipeOut;
        dmaReadCltVec[idx]            = qp.dmaReadClt4SQ;

        // Single rule: dequeue CNP and pulse for exactly one cycle.
        // mkDReg resets to False automatically on cycles where this rule does not fire.
        rule drainCnpAndSignal;
            let cnp = pktMetaDataAndPayloadPipeOutVec[idx].cnpPipeOut.first;
            pktMetaDataAndPayloadPipeOutVec[idx].cnpPipeOut.deq;
            cnpPulseVec[idx] <= True;
        endrule
    end

    let arbitratedDmaReadClt <- mkDmaReadCltArbiter(dmaReadCltVec);

    function Bool isDataStreamFinished(DataStream ds) = ds.isLast;
    let dataStreamPipeOut <- mkPipeOutArbiter(qpDataStreamPipeOutVec, isDataStreamFinished);

    function Bool isWorkCompFinished(WorkComp wc) = True;
    let sendWorkCompPipeOut <- mkPipeOutArbiter(qpSendWorkCompPipeOutVec, isWorkCompFinished);

    interface rdmaDataStreamInput   = toPut(inputDataStreamQ);
    interface workReqInput          = toPut(inputWorkReqQ);
    interface rdmaDataStreamPipeOut = dataStreamPipeOut;
    interface workCompPipeOutSQ     = sendWorkCompPipeOut;
    interface srvPortMetaData       = metaDataSrv;
    interface dmaReadClt            = arbitratedDmaReadClt;
    method Vector#(MAX_QP, Bool) cnpReceived = map(readReg, cnpPulseVec);

endmodule


interface AxiSTransportLayer;
    (* prefix = "s_work_req" *)
    interface RawWorkReqBusSlave rawWorkReqIn;
    // UDP IF
    (* prefix = "s_data_stream" *)
    interface RawDataStreamBusSlave rawRdmaDataStreamIn;
    (* prefix = "m_data_stream" *)
    interface RawDataStreamBusMaster rawRdmaDataStreamOut;
    // CQ
    (* prefix = "m_work_comp_sq" *)
    interface RawWorkCompBusMaster rawWorkCompSQOut;
    // MetaData
    (* prefix = "s_meta_data" *)
    interface RawMetaDataBusSlave rawMetaDataStreamIn;
    (* prefix = "m_meta_data" *)
    interface RawMetaDataBusMaster rawMetaDataStreamOut;
    // DMA Read
    (* prefix = "m_dma_read" *)
    interface RawDmaReadCltBusMaster rawDmaReadCltStreamOut;
    (* prefix = "s_dma_read" *)
    interface RawDmaReadCltBusSlave rawDmaReadCltStreamIn;
    // Per-QP CNP received indicator, packed as a MAX_QP-bit bus
    (* always_ready, result = "cnp_received" *)
    method Bit#(MAX_QP) cnpReceived;
endinterface

(* synthesize *)
module mkAxiSTransportLayer(AxiSTransportLayer);
    TransportLayer transportLayer <- mkTransportLayer;

    let rawWorkReqSlv           <- mkRawWorkReqBusSlave(transportLayer.workReqInput);
    let rawRdmaDataStreamSlv    <- mkRawDataStreamBusSlave(transportLayer.rdmaDataStreamInput);
    let rawRdmaDataStreamMst    <- mkRawDataStreamBusMaster(toGet(transportLayer.rdmaDataStreamPipeOut));
    let rawWorkCompSQMst        <- mkRawWorkCompBusMaster(toGet(transportLayer.workCompPipeOutSQ));
    let rawMetaDataStreamMst    <- mkRawMetaDataBusMaster(transportLayer.srvPortMetaData.response);
    let rawMetaDataStreamSlv    <- mkRawMetaDataBusSlave(transportLayer.srvPortMetaData.request);
    let rawDmaReadCltStreamMst  <- mkRawDmaReadCltBusMaster(transportLayer.dmaReadClt.request);
    let rawDmaReadCltStreamSlv  <- mkRawDmaReadCltBusSlave(transportLayer.dmaReadClt.response);

    interface rawWorkReqIn           = rawWorkReqSlv;
    interface rawRdmaDataStreamIn    = rawRdmaDataStreamSlv;
    interface rawRdmaDataStreamOut   = rawRdmaDataStreamMst;
    interface rawWorkCompSQOut       = rawWorkCompSQMst;
    interface rawMetaDataStreamIn    = rawMetaDataStreamSlv;
    interface rawMetaDataStreamOut   = rawMetaDataStreamMst;
    interface rawDmaReadCltStreamOut = rawDmaReadCltStreamMst;
    interface rawDmaReadCltStreamIn  = rawDmaReadCltStreamSlv;
    // Pack Vector#(MAX_QP, Bool) to Bit#(MAX_QP) for a clean Verilog port
    method Bit#(MAX_QP) cnpReceived = pack(transportLayer.cnpReceived);
endmodule
