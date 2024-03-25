import Connectable :: *;
import FIFOF :: *;
import GetPut :: *;
import PAClib :: *;
import Vector :: *;

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
/*CR
module mkWorkReqAndRecvReqDispatcher#(
    PipeOut#(WorkReq) workReqPipeIn, PipeOut#(RecvReq) recvReqPipeIn
)(Tuple2#(Vector#(MAX_QP, PipeOut#(WorkReq)), Vector#(MAX_QP, PipeOut#(RecvReq))));
*/
module mkWorkReqAndRecvReqDispatcher#(
    PipeOut#(WorkReq) workReqPipeIn
)(Vector#(MAX_QP, PipeOut#(WorkReq)));
    Vector#(MAX_QP, FIFOF#(WorkReq)) workReqOutVec <- replicateM(mkFIFOF);
    //CR Vector#(MAX_QP, FIFOF#(RecvReq)) recvReqOutVec <- replicateM(mkFIFOF);

    rule dispatchWorkReq;
        let wr = workReqPipeIn.first;
        workReqPipeIn.deq;

        let qpIndex = getIndexQP(wr.sqpn);
        workReqOutVec[qpIndex].enq(wr);
        // $display(
        //     "time=%0t:", $time,
        //     " dispatchWorkReq, qpIndex=%0d, sqpn=%h, wr.id=%h",
        //     qpIndex, wr.sqpn, wr.id
        // );
    endrule

   /*CR
    rule dispatchRecvReq;
        let rr = recvReqPipeIn.first;
        recvReqPipeIn.deq;

        let qpIndex = getIndexQP(rr.sqpn);
        recvReqOutVec[qpIndex].enq(rr);
        // $display(
        //     "time=%0t:", $time,
        //     " dispatchWorkReq, qpIndex=%0d, sqpn=%h, rr.id=%h",
        //     qpIndex, rr.sqpn, rr.id
        // );
    endrule
   */

   /*CR
    return tuple2(
        map(toPipeOut, workReqOutVec),
        map(toPipeOut, recvReqOutVec)
    );
   */
   return map(toPipeOut, workReqOutVec);

endmodule

interface TransportLayer;
    //CR interface Put#(RecvReq) recvReqInput;
    interface Put#(WorkReq) workReqInput;
    interface Put#(DataStream) rdmaDataStreamInput;
    interface DataStreamPipeOut rdmaDataStreamPipeOut;
    //CR interface PipeOut#(WorkComp) workCompPipeOutRQ;
    interface PipeOut#(WorkComp) workCompPipeOutSQ;
    interface MetaDataSrv srvPortMetaData;
    interface DmaReadClt  dmaReadClt;
    //CR interface DmaWriteClt dmaWriteClt;

    // method Maybe#(HandlerPD) getPD(QPN qpn);
    // interface Vector#(MAX_QP, rdmaReqRespPipeOut) rdmaReqRespPipeOut;
    // interface Vector#(MAX_QP, RdmaPktMetaDataAndPayloadPipeIn) respPktPipeInVec;
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
    //CR FIFOF#(RecvReq) inputRecvReqQ <- mkFIFOF;

    let pdMetaData   <- mkMetaDataPDs;
    //CR let permCheckSrv <- mkPermCheckSrv(pdMetaData);
    let qpMetaData   <- mkMetaDataQPs;
    let metaDataSrv  <- mkMetaDataSrv(pdMetaData, qpMetaData);

   /*CR
    let { workReqPipeOutVec, recvReqPipeOutVec } <- mkWorkReqAndRecvReqDispatcher(
        toPipeOut(inputWorkReqQ), toPipeOut(inputRecvReqQ)
   );
   */
   let workReqPipeOutVec <- mkWorkReqAndRecvReqDispatcher(
        toPipeOut(inputWorkReqQ)
    );

    // let pktMetaDataAndPayloadPipeOutVec <- mkSimExtractNormalReqResp(
    //     qpMetaData, rdmaReqRespPipeIn
    // );
    let headerAndMetaDataAndPayloadPipeOut <- mkExtractHeaderFromRdmaPktPipeOut(
        rdmaReqRespPipeIn
    );
    let pktMetaDataAndPayloadPipeOutVec <- mkInputRdmaPktBufAndHeaderValidation(
        headerAndMetaDataAndPayloadPipeOut, qpMetaData
    );

    // Vector#(MAX_QP, DataStreamPipeOut)    qpDataStreamPipeOutVec = newVector;
    //CR Vector#(MAX_QP, PipeOut#(WorkComp)) qpRecvWorkCompPipeOutVec = newVector;
    Vector#(MAX_QP, PipeOut#(WorkComp)) qpSendWorkCompPipeOutVec = newVector;

   /*CR
    Vector#(TMul#(2, MAX_QP), DataStreamPipeOut) qpDataStreamPipeOutVec = newVector;
    Vector#(TMul#(2, MAX_QP), PermCheckClt) permCheckCltVec = newVector;
    Vector#(TMul#(2, MAX_QP), DmaReadClt)     dmaReadCltVec = newVector;
   Vector#(TMul#(2, MAX_QP), DmaWriteClt)   dmaWriteCltVec = newVector;
   */
    Vector#(TMul#(1, MAX_QP), DataStreamPipeOut) qpDataStreamPipeOutVec = newVector;
    //CR Vector#(TMul#(1, MAX_QP), PermCheckClt) permCheckCltVec = newVector;
    Vector#(TMul#(1, MAX_QP), DmaReadClt)     dmaReadCltVec = newVector;
    //CR Vector#(TMul#(1, MAX_QP), DmaWriteClt)   dmaWriteCltVec = newVector;

    for (Integer idx = 0; idx < valueOf(MAX_QP); idx = idx + 1) begin
        IndexQP qpIndex = fromInteger(idx);
        let qp = qpMetaData.getQueuePairByIndexQP(qpIndex);

        //CR mkConnection(toGet(recvReqPipeOutVec[idx]), qp.recvReqIn);
        mkConnection(toGet(workReqPipeOutVec[idx]), qp.workReqIn);
       /*CR
        mkConnection(
            pktMetaDataAndPayloadPipeOutVec[idx].reqPktPipeOut,
            qp.reqPktPipeIn
        );
       */
        mkConnection(
            pktMetaDataAndPayloadPipeOutVec[idx].respPktPipeOut,
            qp.respPktPipeIn
        );

        // qpDataStreamPipeOutVec[idx]   = qp.rdmaReqRespPipeOut;
        //CR qpRecvWorkCompPipeOutVec[idx] = qp.workCompPipeOutRQ;
        qpSendWorkCompPipeOutVec[idx] = qp.workCompPipeOutSQ;

        //CR     let leftIdx = 2 * idx;
        //CR     let rightIdx = 2 * idx + 1;
        //CR qpDataStreamPipeOutVec[leftIdx]  = qp.rdmaRespPipeOut;
        //CR     qpDataStreamPipeOutVec[rightIdx] = qp.rdmaReqPipeOut;
        qpDataStreamPipeOutVec[idx] = qp.rdmaReqPipeOut;
        //CR permCheckCltVec[leftIdx]         = qp.permCheckClt4RQ;
        //CR     permCheckCltVec[rightIdx]        = qp.permCheckClt4SQ;
        //CR permCheckCltVec[idx]        = qp.permCheckClt4SQ;
        //CR dmaReadCltVec[leftIdx]           = qp.dmaReadClt4RQ;
        //CR     dmaReadCltVec[rightIdx]          = qp.dmaReadClt4SQ;
        dmaReadCltVec[idx]          = qp.dmaReadClt4SQ;
        //CR dmaWriteCltVec[leftIdx]          = qp.dmaWriteClt4RQ;
        //CR     dmaWriteCltVec[rightIdx]         = qp.dmaWriteClt4SQ;
        //CR dmaWriteCltVec[idx]         = qp.dmaWriteClt4SQ;

        // TODO: support CNP
        let addNoErrWorkCompOutRule <- addRules(genEmptyPipeOutRule(
            pktMetaDataAndPayloadPipeOutVec[idx].cnpPipeOut,
            "pktMetaDataAndPayloadPipeOutVec[" + integerToString(idx) +
            "].cnpPipeOut empty assertion @ mkTransportLayerRDMA"
        ));
    end

    //CR let arbitratedPermCheckClt <- mkPermCheckCltArbiter(permCheckCltVec);
    let arbitratedDmaReadClt   <- mkDmaReadCltArbiter(dmaReadCltVec);
    //CR let arbitratedDmaWriteClt  <- mkDmaWriteCltArbiter(dmaWriteCltVec);

    //CR mkConnection(arbitratedPermCheckClt, permCheckSrv);

    function Bool isDataStreamFinished(DataStream ds) = ds.isLast;
    // TODO: connect to UDP
    let dataStreamPipeOut <- mkPipeOutArbiter(qpDataStreamPipeOutVec, isDataStreamFinished);

    function Bool isWorkCompFinished(WorkComp wc) = True;
    //CR let recvWorkCompPipeOut <- mkPipeOutArbiter(qpRecvWorkCompPipeOutVec, isWorkCompFinished);
    let sendWorkCompPipeOut <- mkPipeOutArbiter(qpSendWorkCompPipeOutVec, isWorkCompFinished);
    // let workCompPipeOut <- mkFixedBinaryPipeOutArbiter(
    //     recvWorkCompPipeOut, sendWorkCompPipeOut
    // );

    interface rdmaDataStreamInput = toPut(inputDataStreamQ);
    interface workReqInput        = toPut(inputWorkReqQ);
    //CR interface recvReqInput        = toPut(inputRecvReqQ);
    // interface srvWorkReqRecvReqWorkComp = toGPServer(inputWorkReqOrRecvReqQ, workCompPipeOut);
    interface rdmaDataStreamPipeOut = dataStreamPipeOut;
    //CR interface workCompPipeOutRQ = recvWorkCompPipeOut;
    interface workCompPipeOutSQ = sendWorkCompPipeOut;

    interface srvPortMetaData = metaDataSrv;
    interface dmaReadClt  = arbitratedDmaReadClt;
    //CR interface dmaWriteClt = arbitratedDmaWriteClt;

    // method Maybe#(HandlerPD) getPD(QPN qpn) = qpMetaData.getPD(qpn);
    // method Maybe#(MetaDataMRs) getMRs4PD(HandlerPD pdHandler) = pdMetaData.getMRs4PD(pdHandler);
endmodule


interface AxiSTransportLayer;
   // SQ
   //CR (* prefix = "s_recv_req" *)
   //CR interface RawRecvReqBusSlave rawRecvReqIn;
   (* prefix = "s_work_req" *)
   interface RawWorkReqBusSlave rawWorkReqIn;
   // UDP IF
   (* prefix = "s_data_stream" *)
   interface RawDataStreamBusSlave rawRdmaDataStreamIn;
   (* prefix = "m_data_stream" *)
   interface RawDataStreamBusMaster rawRdmaDataStreamOut;
   // CQ
   //CR (* prefix = "m_work_comp_rq" *)
   //CR interface RawWorkCompBusMaster rawWorkCompRQOut;
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
   // DMA Write
   //CR (* prefix = "m_dma_write" *)
   //CR interface RawDmaWriteCltBusMaster rawDmaWriteCltStreamOut;
   //CR (* prefix = "s_dma_write" *)
   //CR interface RawDmaWriteCltBusSlave rawDmaWriteCltStreamIn;
endinterface

(* synthesize *)
module mkAxiSTransportLayer(AxiSTransportLayer);
   TransportLayer transportLayer <- mkTransportLayer;

   //CR let rawRecvReqSlv           <- mkRawRecvReqBusSlave(transportLayer.recvReqInput);
   let rawWorkReqSlv           <- mkRawWorkReqBusSlave(transportLayer.workReqInput);
   let rawRdmaDataStreamSlv    <- mkRawDataStreamBusSlave(transportLayer.rdmaDataStreamInput);
   let rawRdmaDataStreamMst    <- mkRawDataStreamBusMaster(toGet(transportLayer.rdmaDataStreamPipeOut));
   //CR let rawWorkCompRQMst        <- mkRawWorkCompBusMaster(toGet(transportLayer.workCompPipeOutRQ));
   let rawWorkCompSQMst        <- mkRawWorkCompBusMaster(toGet(transportLayer.workCompPipeOutSQ));
   let rawMetaDataStreamMst    <- mkRawMetaDataBusMaster(transportLayer.srvPortMetaData.response);
   let rawMetaDataStreamSlv    <- mkRawMetaDataBusSlave(transportLayer.srvPortMetaData.request);
   let rawDmaReadCltStreamMst  <- mkRawDmaReadCltBusMaster(transportLayer.dmaReadClt.request);
   let rawDmaReadCltStreamSlv  <- mkRawDmaReadCltBusSlave(transportLayer.dmaReadClt.response);
   //CR let rawDmaWriteCltStreamMst <- mkRawDmaWriteCltBusMaster(transportLayer.dmaWriteClt.request);
   //CR let rawDmaWriteCltStreamSlv <- mkRawDmaWriteCltBusSlave(transportLayer.dmaWriteClt.response);

   //CR interface rawRecvReqIn            = rawRecvReqSlv;
   interface rawWorkReqIn            = rawWorkReqSlv;
   interface rawRdmaDataStreamIn     = rawRdmaDataStreamSlv;
   interface rawRdmaDataStreamOut    = rawRdmaDataStreamMst;
   //CR interface rawWorkCompRQOut        = rawWorkCompRQMst;
   interface rawWorkCompSQOut        = rawWorkCompSQMst;
   interface rawMetaDataStreamIn     = rawMetaDataStreamSlv;
   interface rawMetaDataStreamOut    = rawMetaDataStreamMst;
   interface rawDmaReadCltStreamOut  = rawDmaReadCltStreamMst;
   interface rawDmaReadCltStreamIn   = rawDmaReadCltStreamSlv;
   //CR interface rawDmaWriteCltStreamOut = rawDmaWriteCltStreamMst;
   //CR interface rawDmaWriteCltStreamIn  = rawDmaWriteCltStreamSlv;
endmodule
