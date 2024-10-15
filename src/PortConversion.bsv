import DataTypes :: *;
import Headers :: *;
import PrimUtils :: *;
import MetaData :: *;
import GetPut :: *;
import Connectable :: *;

import SemiFifo :: *;
import BusConversion :: *;


(* always_ready, always_enabled *)
interface RawDataStreamBusSlave;
   (* prefix = "" *)
   method Action validData(
      (* port = "tvalid" *) Bool valid,
      (* port = "tdata"  *) DATA data,
      (* port = "tkeep"  *) ByteEn byteEn,
      (* port = "tfirst" *) Bool isFirst,
      (* port = "tlast"  *) Bool isLast
      );

   (* result = "tready" *) method Bool ready;
endinterface

(* always_ready, always_enabled *)
interface RawDataStreamBusMaster;
   (* result = "tvalid"*) method Bool valid;
   (* result = "tdata" *) method DATA data;
   (* result = "tkeep" *) method ByteEn byteEn;
   (* result = "tfirst"*) method Bool isFirst;
   (* result = "tlast" *) method Bool isLast;

   (* prefix = "" *)
   method Action ready((* port = "tready" *) Bool rdy);
endinterface

(* always_ready, always_enabled *)
interface RawRecvReqBusSlave;
   (* prefix = "" *)
   method Action validData(
      (* port = "valid" *) Bool valid,
      (* port = "id"    *) WorkReqID id,
      (* port = "len"   *) Length len,
      (* port = "laddr" *) ADDR lAddr,
      (* port = "lkey"  *) LKEY lKey,
      (* port = "sqpn"  *) QPN sqpn
      );

   (* result = "ready" *) method Bool ready;
endinterface

(* always_ready, always_enabled *)
interface RawWorkReqBusSlave;
   (* prefix = "" *)
   method Action validData(
      (* port = "valid"       *) Bool valid,
      (* port = "id"          *) WorkReqID id,
      (* port = "op_code"     *) WorkReqOpCode opCode,
      (* port = "flags"       *) FlagsType#(WorkReqSendFlag) flags,
      (* port = "raddr"       *) ADDR rAddr,
      (* port = "rkey"        *) RKEY rKey,
      (* port = "len"         *) Length len,
      (* port = "laddr"       *) ADDR lAddr,
      (* port = "lkey"        *) LKEY lKey,
      (* port = "sqpn"        *) QPN sqpn,
      (* port = "solicited"   *) Bool solicited,
      (* port = "comp"        *) Maybe#(Long) comp,
      (* port = "swap"        *) Maybe#(Long) swap,
      (* port = "imm_dt"      *) Maybe#(IMM) immDt,
      (* port = "rkey_to_inv" *) Maybe#(RKEY) rkey2Inv,
      (* port = "srqn"        *) Maybe#(QPN) srqn,
      (* port = "dqpn"        *) Maybe#(QPN) dqpn,
      (* port = "qkey"        *) Maybe#(QKEY) qkey
      );

   (* result = "ready" *) method Bool ready;
endinterface

(* always_ready, always_enabled *)
interface RawWorkCompBusMaster;
   (* result = "valid"       *) method Bool valid;
   (* result = "id"          *) method WorkReqID id;
   (* result = "op_code"      *) method WorkCompOpCode opcode;
   (* result = "flags"       *) method WorkCompFlags flags;
   (* result = "status"      *) method WorkCompStatus status;
   (* result = "len"         *) method Length len;
   (* result = "pkey"        *) method PKEY pKey;
   (* result = "qpn"         *) method QPN qpn;
   (* result = "imm_dt"      *) method Maybe#(IMM) immDt;
   (* result = "rkey_to_inv" *) method Maybe#(RKEY) rkey2Inv;

   (* prefix = "" *)
   method Action ready((* port = "ready" *) Bool rdy);
endinterface

(* always_ready, always_enabled *)
interface RawMetaDataBusMaster;
   (* result = "tvalid"          *) method Bool valid;
   (* result = "tdata" *) method MetaDataResp metaDataResp;

   (* prefix = "" *)
   method Action ready((* port = "tready" *) Bool rdy);
endinterface

(* always_ready, always_enabled *)
interface RawMetaDataBusSlave;
   (* prefix = "" *)
   method Action validData(
      (* port = "tvalid"          *) Bool valid,
      (* port = "tdata"  *) MetaDataReq metaDataReq
      );

   (* result = "tready" *) method Bool ready;
endinterface

(* always_ready, always_enabled *)
interface RawDmaReadCltBusMaster;
   (* result = "valid"       *) method Bool valid;
   (* result = "initiator"   *) method DmaReqSrcType initiator;
   (* result = "sqpn"        *) method QPN sqpn;
   (* result = "wr_id"       *) method WorkReqID wrID;
   (* result = "start_addr"  *) method ADDR startAddr;
   (* result = "len"         *) method PktLen len;
   (* result = "mr_idx"      *) method IndexMR mrIdx;

   (* prefix = "" *)
   method Action ready((* port = "ready" *) Bool rdy);
endinterface

(* always_ready, always_enabled *)
interface RawDmaReadCltBusSlave;
   (* prefix = "" *)
   method Action validData(
      (* port = "valid"       *) Bool valid,
      (* port = "initiator"   *) DmaReqSrcType initiator,
      (* port = "sqpn"        *) QPN sqpn,
      (* port = "wr_id"       *) WorkReqID wrID,
      (* port = "is_resp_err" *) Bool isRespErr,
      (* port = "data_stream" *) DataStream dataStream
      );

   (* result = "ready" *) method Bool ready;
endinterface

(* always_ready, always_enabled *)
interface RawDmaReadSrvBusMaster;
   (* result = "valid"       *) method Bool valid;
   (* result = "initiator"   *) method DmaReqSrcType initiator;
   (* result = "sqpn"        *) method QPN sqpn;
   (* result = "wr_id"       *) method WorkReqID wrID;
   (* result = "is_resp_err" *) method Bool isRespErr;
   (* result = "data_stream" *) method DataStream dataStream;

   (* prefix = "" *)
   method Action ready((* port = "ready" *) Bool rdy);
endinterface

(* always_ready, always_enabled *)
interface RawDmaReadSrvBusSlave;
   (* prefix = "" *)
      method Action validData(
         (* port = "valid"       *) Bool valid,
         (* port = "initiator"   *) DmaReqSrcType initiator,
         (* port = "sqpn"        *) QPN sqpn,
         (* port = "wr_id"       *) WorkReqID wrID,
         (* port = "start_addr"  *) ADDR startAddr,
         (* port = "len"         *) PktLen len,
         (* port = "mr_idx"      *) IndexMR mrIdx
         );

   (* result = "ready" *) method Bool ready;
endinterface

(* always_ready, always_enabled *)
interface RawDmaWriteCltBusMaster;
   (* result = "valid"       *) method Bool valid;
   (* result = "meta_data"   *) method DmaWriteMetaData metaData;
   (* result = "data_stream" *) method DataStream dataStream;

   (* prefix = "" *)
   method Action ready((* port = "ready" *) Bool rdy);
endinterface

(* always_ready, always_enabled *)
interface RawDmaWriteCltBusSlave;
   (* prefix = "" *)
   method Action validData(
      (* port = "valid"       *) Bool valid,
      (* port = "initiator"   *) DmaReqSrcType initiator,
      (* port = "sqpn"        *) QPN sqpn,
      (* port = "psn"         *) PSN psn,
      (* port = "is_resp_err" *) Bool isRespErr
      );

   (* result = "ready" *) method Bool ready;
endinterface

/*
module mkRawDataStreamBusMaster#(DataStreamPipeOut pipe)(RawDataStreamBusMaster);
    RawBusMaster#(DataStream) rawBus <- mkPipeOutToRawBusMaster(pipe);

    method Bool valid    = rawBus.valid;
    method ByteEn byteEn = rawBus.data.byteEn;
    method DATA data     = rawBus.data.data;
    method Bool isFirst  = rawBus.data.isFirst;
    method Bool isLast   = rawBus.data.isLast;

    method Action ready(Bool rdy);
        rawBus.ready(rdy);
    endmethod
endmodule
*/
module mkRawDataStreamBusMaster#(Get#(DataStream) getOut)(RawDataStreamBusMaster);
    RawBusMaster#(DataStream) rawBus <- mkGetToRawBusMaster(getOut, CF);

    method Bool valid    = rawBus.valid;
    method ByteEn byteEn = rawBus.data.byteEn;
    method DATA data     = rawBus.data.data;
    method Bool isFirst  = rawBus.data.isFirst;
    method Bool isLast   = rawBus.data.isLast;

    method Action ready(Bool rdy);
        rawBus.ready(rdy);
    endmethod
endmodule

module mkRawDataStreamBusSlave#(Put#(DataStream) putIn)(RawDataStreamBusSlave);
    RawBusSlave#(DataStream) rawBus <- mkPutToRawBusSlave(putIn, CF);

    method Action validData(
        Bool   valid,
        DATA   data,
        ByteEn byteEn,
        Bool   isFirst,
        Bool   isLast
    );
        DataStream dataStream = DataStream {
            data   : data,
            byteEn : byteEn,
            isFirst: isFirst,
            isLast : isLast
        };
        rawBus.validData(valid, dataStream);
    endmethod
    method Bool ready = rawBus.ready;
endmodule

module mkRawRecvReqBusSlave#(Put#(RecvReq) putIn)(RawRecvReqBusSlave);
   RawBusSlave#(RecvReq) rawBus <- mkPutToRawBusSlave(putIn, CF);

   method Action validData(
      Bool      valid,
      WorkReqID id,
      Length    len,
      ADDR      lAddr,
      LKEY      lKey,
      QPN       sqpn
      );
      RecvReq recvReq = RecvReq {
         id    : id,
         len   : len,
         laddr : lAddr,
         lkey  : lKey,
         sqpn  : sqpn
         };
      rawBus.validData(valid, recvReq);
   endmethod

   method Bool ready = rawBus.ready;

endmodule


module mkRawWorkReqBusSlave#(Put#(WorkReq) putIn)(RawWorkReqBusSlave);
   RawBusSlave#(WorkReq) rawBus <- mkPutToRawBusSlave(putIn, CF);

   method Action validData(
      Bool                        valid,
      WorkReqID                   id,
      WorkReqOpCode               opCode,
      FlagsType#(WorkReqSendFlag) flags,
      ADDR                        rAddr,
      RKEY                        rKey,
      Length                      len,
      ADDR                        lAddr,
      LKEY                        lKey,
      QPN                         sqpn,
      Bool                        solicited,
      Maybe#(Long)                comp,
      Maybe#(Long)                swap,
      Maybe#(IMM)                 immDt,
      Maybe#(RKEY)                rkey2Inv,
      Maybe#(QPN)                 srqn,
      Maybe#(QPN)                 dqpn,
      Maybe#(QKEY)                qkey
      );
      WorkReq workReq = WorkReq {
         id        : id,
         opcode    : opCode,
         flags     : flags,
         raddr     : rAddr,
         rkey      : rKey,
         len       : len,
         laddr     : lAddr,
         lkey      : lKey,
         sqpn      : sqpn,
         solicited : solicited,
         comp      : comp,
         swap      : swap,
         immDt     : immDt,
         rkey2Inv  : rkey2Inv,
         srqn      : srqn,
         dqpn      : dqpn,
         qkey      : qkey
         };
      rawBus.validData(valid, workReq);
   endmethod

   method Bool ready = rawBus.ready;

endmodule

/*
module mkRawWorkCompBusMaster#(PipeOut#(WorkComp) pipe)(RawWorkCompBusMaster);
    RawBusMaster#(WorkComp) rawBus <- mkPipeOutToRawBusMaster(pipe);

    method Bool valid            = rawBus.valid;
    method WorkReqID id          = rawBus.data.id;
    method WorkCompOpCode opcode = rawBus.data.opcode;
    method WorkCompFlags flags   = rawBus.data.flags;
    method WorkCompStatus status = rawBus.data.status;
    method Length len            = rawBus.data.len;
    method PKEY pKey             = rawBus.data.qkey;
    method QPN qpn               = rawBus.data.qpn;
    method Maybe#(IMM) immDt     = rawBus.data.immDt;
    method Maybe#(RKEY) rkey2Inv = rawBus.data.rkey2Inv;

    method Action ready(Bool rdy);
        rawBus.ready(rdy);
    endmethod
endmodule
*/

module mkRawWorkCompBusMaster#(Get#(WorkComp) getOut)(RawWorkCompBusMaster);
    RawBusMaster#(WorkComp) rawBus <- mkGetToRawBusMaster(getOut, CF);

    method Bool valid            = rawBus.valid;
    method WorkReqID id          = rawBus.data.id;
    method WorkCompOpCode opcode = rawBus.data.opcode;
    method WorkCompFlags flags   = rawBus.data.flags;
    method WorkCompStatus status = rawBus.data.status;
    method Length len            = rawBus.data.len;
    method PKEY pKey             = rawBus.data.pkey;
    method QPN qpn               = rawBus.data.qpn;
    method Maybe#(IMM) immDt     = rawBus.data.immDt;
    method Maybe#(RKEY) rkey2Inv = rawBus.data.rkey2Inv;

    method Action ready(Bool rdy);
        rawBus.ready(rdy);
    endmethod
endmodule

module mkRawMetaDataBusSlave#(Put#(MetaDataReq) putIn)(RawMetaDataBusSlave);
   RawBusSlave#(MetaDataReq) rawBus <- mkPutToRawBusSlave(putIn, CF);

   method Action validData(
      Bool valid,
      MetaDataReq metaDataReq
      );
      rawBus.validData(valid, metaDataReq);
   endmethod

   method Bool ready = rawBus.ready;
endmodule

module mkRawMetaDataBusMaster#(Get#(MetaDataResp) getOut)(RawMetaDataBusMaster);
   RawBusMaster#(MetaDataResp) rawBus <- mkGetToRawBusMaster(getOut, CF);

   method Bool valid                = rawBus.valid;
   method MetaDataResp metaDataResp = rawBus.data;

   method Action ready(Bool rdy);
      rawBus.ready(rdy);
   endmethod
endmodule

module mkRawDmaReadCltBusMaster#(Get#(DmaReadReq) getOut)(RawDmaReadCltBusMaster);
   RawBusMaster#(DmaReadReq) rawBus <- mkGetToRawBusMaster(getOut, CF);

   method Bool valid              = rawBus.valid;
   method DmaReqSrcType initiator = rawBus.data.initiator;
   method QPN sqpn                = rawBus.data.sqpn;
   method WorkReqID wrID          = rawBus.data.wrID;
   method ADDR startAddr          = rawBus.data.startAddr;
   method PktLen len              = rawBus.data.len;
   method IndexMR mrIdx           = rawBus.data.mrIdx;

   method Action ready(Bool rdy);
      rawBus.ready(rdy);
   endmethod
endmodule

module mkRawDmaReadCltBusSlave#(Put#(DmaReadResp) putIn)(RawDmaReadCltBusSlave);
   RawBusSlave#(DmaReadResp) rawBus <- mkPutToRawBusSlave(putIn, CF);

   method Action validData(
      Bool valid,
      DmaReqSrcType initiator,
      QPN sqpn,
      WorkReqID wrID,
      Bool isRespErr,
      DataStream dataStream
      );
   DmaReadResp dmaReadResp = DmaReadResp{
      initiator  : initiator,
      sqpn       : sqpn,
      wrID       : wrID,
      isRespErr  : isRespErr,
      dataStream : dataStream
      };
      rawBus.validData(valid, dmaReadResp);
   endmethod

   method Bool ready = rawBus.ready;
endmodule

module mkRawDmaReadSrvBusMaster#(Get#(DmaReadResp) getOut)(RawDmaReadSrvBusMaster);
   RawBusMaster#(DmaReadResp) rawBus <- mkGetToRawBusMaster(getOut, CF);

   method Bool valid              = rawBus.valid;
   method DmaReqSrcType initiator = rawBus.data.initiator;
   method QPN sqpn                = rawBus.data.sqpn;
   method WorkReqID wrID          = rawBus.data.wrID;
   method Bool isRespErr          = rawBus.data.isRespErr;
   method DataStream dataStream   = rawBus.data.dataStream;

   method Action ready(Bool rdy);
      rawBus.ready(rdy);
   endmethod
endmodule

module mkRawDmaReadSrvBusSlave#(Put#(DmaReadReq) putIn)(RawDmaReadSrvBusSlave);
   RawBusSlave#(DmaReadReq) rawBus <- mkPutToRawBusSlave(putIn, CF);

   method Action validData(
      Bool valid,
      DmaReqSrcType initiator,
      QPN sqpn,
      WorkReqID wrID,
      ADDR startAddr,
      PktLen len,
      IndexMR mrIdx
      );
      DmaReadReq dmaReadReq = DmaReadReq{
         initiator  : initiator,
         sqpn       : sqpn,
         wrID       : wrID,
         startAddr  : startAddr,
         len        : len,
         mrIdx      : mrIdx
         };
      rawBus.validData(valid, dmaReadReq);
   endmethod

   method Bool ready = rawBus.ready;
endmodule























module mkRawDmaWriteCltBusMaster#(Get#(DmaWriteReq) getOut)(RawDmaWriteCltBusMaster);
   RawBusMaster#(DmaWriteReq) rawBus <- mkGetToRawBusMaster(getOut, CF);

   method Bool valid                = rawBus.valid;
   method DmaWriteMetaData metaData = rawBus.data.metaData;
   method DataStream dataStream     = rawBus.data.dataStream;

   method Action ready(Bool rdy);
      rawBus.ready(rdy);
   endmethod
endmodule

module mkRawDmaWriteCltBusSlave#(Put#(DmaWriteResp) putIn)(RawDmaWriteCltBusSlave);
   RawBusSlave#(DmaWriteResp) rawBus <- mkPutToRawBusSlave(putIn, CF);

   method Action validData(
      Bool valid,
      DmaReqSrcType initiator,
      QPN sqpn,
      PSN psn,
      Bool isRespErr
      );
   DmaWriteResp dmaWriteResp = DmaWriteResp{
      initiator  : initiator,
      sqpn       : sqpn,
      psn        : psn,
      isRespErr  : isRespErr
      };
      rawBus.validData(valid, dmaWriteResp);
   endmethod

   method Bool ready = rawBus.ready;
endmodule
