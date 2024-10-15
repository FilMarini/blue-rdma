import ClientServer :: *;
import Cntrs :: *;
import FIFOF :: *;
import GetPut :: *;
import PAClib :: *;
import Randomizable :: *;
import Vector :: *;

import DataTypes :: *;
import Headers :: *;
import PrimUtils :: *;
import Settings :: *;
import Utils :: *;
import Utils4Dma :: *;
import PortConversion :: *;

module mkDmaReadRandSrv(DmaReadSrv);
   FIFOF#(DmaReadReq)      dmaReadReqQ <- mkFIFOF;
   FIFOF#(DmaReadResp)    dmaReadRespQ <- mkFIFOF;

   DataStreamPipeOut randomDataStreamPipeOut <- mkGenericRandomPipeOut;

   Reg#(TotalFragNum) remainingFragNumReg <- mkRegU;
   Reg#(Bool) busyReg <- mkReg(False);
   Reg#(Bool) isFirstReg <- mkRegU;
   Reg#(ByteEn) lastFragByteEnReg <- mkRegU;
   Reg#(BusBitNum) lastFragInvalidBitNumReg <- mkRegU;
   Reg#(DmaReadReq) curReqReg <- mkRegU;
   
   Bool isFragCntZero = isZero(remainingFragNumReg);

   rule acceptReq if (!busyReg);
      let dmaReadReq = dmaReadReqQ.first;
      dmaReadReqQ.deq;

      let isZeroLen = isZero(dmaReadReq.len);
      immAssert(
         !isZeroLen,
         "dmaReadReq.len non-zero assrtion",
         $format("dmaReadReq.len=%0d should not be zero", dmaReadReq.len)
         );

      let { totalFragCnt, lastFragByteEn, lastFragValidByteNum } =
      calcTotalFragNumByLength(zeroExtend(dmaReadReq.len));
      let { lastFragValidBitNum, lastFragInvalidByteNum, lastFragInvalidBitNum } =
      calcFragBitNumAndByteNum(lastFragValidByteNum);

      remainingFragNumReg <= isZeroLen ? 0 : totalFragCnt - 1;
      lastFragByteEnReg <= lastFragByteEn;
      lastFragInvalidBitNumReg <= lastFragInvalidBitNum;

      immAssert(
         !isZero(lastFragByteEn),
         "lastFragByteEn non-zero assertion",
         $format(
                 "lastFragByteEn=%h should not have zero ByteEn, dmaReadReq.len=%0d",
                 lastFragByteEn, dmaReadReq.len
                 )
         );

      curReqReg <= dmaReadReq;
      busyReg <= True;
      isFirstReg <= True;

      // $display(
      //     "time=%0t: mkSimDmaReadSrvAndReqRespPipeOut acceptReq", $time,
      //     ", DMA read request, wr.id=%h, dmaReadReq.len=%0d, totalFragCnt=%0d",
      //     dmaReadReq.wrID, dmaReadReq.len, totalFragCnt
      // );
   endrule

   rule genResp if (busyReg);
      remainingFragNumReg <= remainingFragNumReg - 1;
      let dataStream = randomDataStreamPipeOut.first;
      randomDataStreamPipeOut.deq;

      dataStream.isFirst = isFirstReg;
      isFirstReg <= False;
      dataStream.isLast = isFragCntZero;
      dataStream.byteEn = maxBound;

      if (isFragCntZero) begin
         busyReg <= False;
         dataStream.byteEn = lastFragByteEnReg;
         DATA tmpData = dataStream.data >> lastFragInvalidBitNumReg;
         dataStream.data = truncate(tmpData << lastFragInvalidBitNumReg);
      end

      let resp = DmaReadResp {
         initiator : curReqReg.initiator,
         sqpn      : curReqReg.sqpn,
         wrID      : curReqReg.wrID,
         isRespErr : False,
         dataStream: dataStream
         };

      dmaReadRespQ.enq(resp);

      immAssert(
         !isZero(dataStream.byteEn),
         "dmaReadResp.data.byteEn non-zero assertion",
         $format("dmaReadResp.data should not have zero ByteEn, ", fshow(dataStream))
         );

      // $display(
      //     "time=%0t: mkSimDmaReadSrvAndReqRespPipeOut genResp", $time,
      //     ", DMA read response, wr.id=%h, remainingFragNum=%0d",
      //     curReqReg.wrID, remainingFragNumReg,
      //     // ", dataStream=", fshow(dataStream)
      //     ", dataStream.isFirst=", fshow(dataStream.isFirst),
      //     ", dataStream.isLast=", fshow(dataStream.isLast)
      // );
   endrule

   return toGPServer(dmaReadReqQ, dmaReadRespQ);
endmodule

interface AxiSDmaReadRandSrv;
   // DMA Read
   (* prefix = "m_dma_read" *)
   interface RawDmaReadSrvBusMaster rawDmaReadSrvStreamOut;
   (* prefix = "s_dma_read" *)
   interface RawDmaReadSrvBusSlave rawDmaReadSrvStreamIn;
endinterface

(* synthesize *)
module mkAxiSDmaReadRandSrv(AxiSDmaReadRandSrv);
   DmaReadSrv dmaReadRandSrv <- mkDmaReadRandSrv;
   
   let rawDmaReadSrvStreamMst  <- mkRawDmaReadSrvBusMaster(dmaReadRandSrv.response);
   let rawDmaReadSrvStreamSlv  <- mkRawDmaReadSrvBusSlave(dmaReadRandSrv.request);

   interface rawDmaReadSrvStreamOut  = rawDmaReadSrvStreamMst;
   interface rawDmaReadSrvStreamIn   = rawDmaReadSrvStreamSlv;
endmodule
