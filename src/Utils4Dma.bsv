import BuildVector :: *;
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

module mkGenericRandomPipeOut(PipeOut#(anytype)) provisos(
   Bits#(anytype, tSz), Bounded#(anytype)
   );
   Randomize#(anytype) randomGen <- mkGenericRandomizer;
   FIFOF#(anytype) randomValQ <- mkFIFOF;

   Reg#(Bool) initializedReg <- mkReg(False);

   rule init if (!initializedReg);
      randomGen.cntrl.init;
      initializedReg <= True;
   endrule

   rule gen if (initializedReg);
      let val <- randomGen.next;
      randomValQ.enq(val);
   endrule

   return toPipeOut(randomValQ);
endmodule

function Tuple3#(TotalFragNum, ByteEn, ByteEnBitNum) calcTotalFragNumByLength(Length dmaLen);
   Bit#(DATA_BUS_BYTE_NUM_WIDTH) lastFragByteNumResidue = truncate(dmaLen);
   Bit#(TSub#(RDMA_MAX_LEN_WIDTH, DATA_BUS_BYTE_NUM_WIDTH)) truncatedLen = truncateLSB(dmaLen);
   let lastFragEmpty = isZero(lastFragByteNumResidue);
   TotalFragNum fragNum = zeroExtend(truncatedLen + zeroExtend(pack(!lastFragEmpty)));

   ByteEnBitNum lastFragValidByteNum = lastFragEmpty ?
   fromInteger(valueOf(DATA_BUS_BYTE_WIDTH)) :
   zeroExtend(lastFragByteNumResidue);
   ByteEn lastFragByteEn = genByteEn(lastFragValidByteNum);
   return tuple3(fragNum, lastFragByteEn, lastFragValidByteNum);
endfunction
