import os
import random
import logging

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import cocotb_test.simulator
from cocotbext.axi import AxiStreamBus, AxiStreamSource, AxiStreamSink, AxiStreamFrame
from bitstring import Bits, BitArray, BitStream, pack
from cocotb.queue import Queue

from TestUtils import *
from BusStructs import *
from DmaPyServer import *

# Settings
# Number of tests
CASES_NUM = 2
# MetaData settings
PD_NUM = 2
QP_NUM = 4
MR_NUM = 4

class AxisTransportLayerTester:
    def __init__(
            self, dut, casesNum, pdNum, qpNum, mrNum
    ):
        self.dut = dut
        self.log = logging.getLogger("TestAxiSTransportLayerTester")
        self.log.setLevel(logging.DEBUG)
        # Sim settings
        self.casesNum = casesNum
        self.pdNum = pdNum
        self.qpNum = qpNum
        # Input values (Temporary! TODO)
        self.dqpnVec = []
        self.rKeyVec = []
        for caseIdx in range(self.qpNum):
            self.dqpnVec.append(random.getrandbits(QPA_DQPN_B))
            self.rKeyVec.append(random.getrandbits(MR_RKEY_B))
        self.mrNum = mrNum
        # Used signals
        self.pdHandlerVec4Req = []
        self.lKeyVec4Write = []
        self.qpnVec = []
        self.qpnVec4RTS = []
        self.sqpnVec4Write = []
        self.qpiTypeVec = []
        self.dmaRCRespsQ = Queue(maxsize=qpNum)
        # Clock
        self.clock = self.dut.CLK
        # Reset
        self.resetn = self.dut.RST_N
        #DataStreamAxisMaster
        self.data_stream_sink = AxiStreamSink(
            AxiStreamBus.from_prefix(dut, "m_data_stream"),
            self.clock,
            self.resetn,
            False
        )
        # DataStreamAxisSlave
        self.data_stream_src = AxiStreamSource(
            AxiStreamBus.from_prefix(dut, "s_data_stream"),
            self.clock,
            self.resetn,
            False
        )
        # RecvReqAxisSlave
        self.recv_req_src = RecvReqSource(
            RecvReqBus.from_prefix(dut, "s_recv_req"),
            self.clock,
            self.resetn,
            False,
        )
        # WorkReqAxisSlave
        self.work_req_src = WorkReqSource(
            WorkReqBus.from_prefix(dut, "s_work_req"),
            self.clock,
            self.resetn,
            False,
        )
        # WorkCompRQAxisMaster
        self.work_comp_rq_sink = WorkCompSink(
            WorkCompBus.from_prefix(dut, "m_work_comp_rq"),
            self.clock,
            self.resetn,
            False,
        )
        # WorkCompSQAxisMaster
        self.work_comp_rq_sink = WorkCompSink(
            WorkCompBus.from_prefix(dut, "m_work_comp_sq"),
            self.clock,
            self.resetn,
            False,
        )
        #MetaDataAxisMaster
        self.meta_data_sink = MetaDataSink(
            MetaDataBus.from_prefix(dut, "m_meta_data"),
            self.clock,
            self.resetn,
            False,
        )
        # MetaDataAxisSlave
        self.meta_data_src = MetaDataSource(
            MetaDataBus.from_prefix(dut, "s_meta_data"),
            self.clock,
            self.resetn,
            False,
        )
        # DmaReadCltAxisMaster
        self.dma_read_clt_sink = DmaReadCltReqSink(
            DmaReadCltReqBus.from_prefix(dut, "m_dma_read"),
            self.clock,
            self.resetn,
            False,
        )
        # DmaReadCltAxisSlave
        self.dma_read_clt_src = DmaReadCltRespSource(
            DmaReadCltRespBus.from_prefix(dut, "s_dma_read"),
            self.clock,
            self.resetn,
            False,
        )
        # DmaWriteCltAxisMaster
        self.dma_write_clt_sink = DmaWriteCltReqSink(
            DmaWriteCltReqBus.from_prefix(dut, "m_dma_write"),
            self.clock,
            self.resetn,
            False,
        )
        # DmaReadCltAxisMaster
        self.dma_write_clt_src = DmaWriteCltRespSource(
            DmaWriteCltRespBus.from_prefix(dut, "s_dma_write"),
            self.clock,
            self.resetn,
            False,
        )

    async def gen_clock(self):
        await cocotb.start(Clock(self.clock, 10, "ns").start())
        self.log.info("Start generating clock")

    async def gen_reset(self):
        self.resetn.value = 0
        await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        self.resetn.value = 1
        await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        await RisingEdge(self.clock)
        self.log.info("Complete Reset dut")

    async def req_alloc_pd(self):
        for caseIdx in range(self.pdNum):
            allocOrNot = BitStream(uint = 1, length = PD_ALLOC_OR_NOT_B)
            pdKey = BitStream(uint = random.getrandbits(PD_KEY_B), length = PD_KEY_B)
            pdReq = reqPd(allocOrNot = allocOrNot, pdKey = pdKey)
            metaData = MetaDataTransaction()
            metaData.tdata = pdReq.getBusValue()
            await self.meta_data_src.send(metaData)

    async def resp_alloc_pd(self):
        for caseIdx in range(self.pdNum):
            dut_alloc_pd_resp = await self.meta_data_sink.recv()
            metaRespBus = BitStream(uint = dut_alloc_pd_resp.tdata.integer, length = META_DATA_BITS)
            pdResp = respPd(metaRespBus)
            if not pdResp.successOrNot:
                self.log.error("Creation of PD not successfull!")
            if pdResp.busType.uint != METADATA_PD_T:
                self.log.error(f'Bus type should be {METADATA_PD_T}, instead decoded {pdResp.busType.uint}')
            self.log.info(f'pdHandler for PD {caseIdx}: {pdResp.pdHandler.hex}, {pdResp.pdHandler.bin}')
            self.log.debug(f'pdKey for PD {caseIdx}: {pdResp.pdKey.bin}')
            self.pdHandlerVec4Req.append(pdResp.pdHandler.uint)

    async def req_alloc_mr(self):
        for caseIdx in range(self.mrNum):
            pdHandler = self.pdHandlerVec4Req[caseIdx % self.pdNum]

            allocOrNot = BitStream(uint = 1, length = MR_ALLOC_OR_NOT_B)
            mrLAddr = BitStream(uint = DEFAULT_ADDR, length = MR_LADDR_B)
            mrLen = BitStream(uint = DEFAULT_LEN, length = MR_LEN_B)
            mrAccFlags = BitStream(uint = ACC_PERM, length = MR_ACCFLAGS_B)
            mrPdHandler = BitStream(uint = pdHandler, length = MR_PDHANDLER_B)
            mrLKeyPart = BitStream(uint = random.getrandbits(MR_LKEYPART_B), length = MR_LKEYPART_B)
            mrRKeyPart = BitStream(uint = random.getrandbits(MR_RKEYPART_B), length = MR_RKEYPART_B)
            lKeyOrNot = BitStream(uint = 0, length = 1)
            mrReq = reqMr(allocOrNot = allocOrNot, mrLAddr = mrLAddr, mrLen = mrLen, mrAccFlags = mrAccFlags,
                          mrPdHandler = mrPdHandler, mrLKeyPart = mrLKeyPart, mrRkeyPart = mrRKeyPart,
                          lKeyOrNot = lKeyOrNot)
            metaData = MetaDataTransaction()
            metaData.tdata = mrReq.getBusValue()
            await self.meta_data_src.send(metaData)

    async def resp_alloc_mr(self):
        for caseIdx in range(self.mrNum):
            dut_alloc_mr_resp = await self.meta_data_sink.recv()
            metaRespBus = BitStream(uint = dut_alloc_mr_resp.tdata.integer, length = META_DATA_BITS)
            mrResp = respMr(metaRespBus)
            if not mrResp.successOrNot:
                self.log.error("Creation of MR not successfull!")
            if mrResp.busType.uint != METADATA_MR_T:
                self.log.error(f'Bus type should be {METADATA_MR_T}, instead decoded {mrResp.busType.uint}')
            self.log.debug(f'lKey for write for MR {caseIdx}: {mrResp.lKey.hex}')
            self.lKeyVec4Write.append(mrResp.lKey.uint)

    async def req_create_qp(self):
        for caseIdx in range(self.qpNum):
            pdHandler = self.pdHandlerVec4Req[caseIdx % self.pdNum]

            qpReqType = BitStream(uint = REQ_QP_CREATE, length = QP_REQTYPE_B)
            qpPdHandler = BitStream(uint = pdHandler, length = QP_PDHANDLER_B)
            qpiType = BitStream(uint = IBV_QPT_XRC_SEND, length = QPI_TYPE_B)
            qpiSqSigAll = BitStream(uint = 0, length = QPI_SQSIGALL_B)
            qpReq = reqQp(pdHandler = qpPdHandler, qpReqType = qpReqType, qpiType = qpiType, qpiSqSigAll = qpiSqSigAll)

            metaData = MetaDataTransaction()
            metaData.tdata = qpReq.getBusValue()
            await self.meta_data_src.send(metaData)

    async def resp_create_qp(self):
        for caseIdx in range(self.qpNum):
            dut_alloc_qp_resp = await self.meta_data_sink.recv()
            metaRespBus = BitStream(uint = dut_alloc_qp_resp.tdata.integer, length = META_DATA_BITS)
            qpResp = respQp(metaRespBus)
            if not qpResp.successOrNot:
                self.log.error("Creation of QP not successfull!")
            if qpResp.busType.uint != METADATA_QP_T:
                self.log.error(f'Bus type should be {METADATA_QP_T}, instead decoded {qpResp.busType.uint}')
            self.log.debug(f'QPN for QP {caseIdx}: {qpResp.qpn.hex}')
            self.qpnVec.append(qpResp.qpn.uint)
            self.qpiTypeVec.append(qpResp.qpiType.uint)

    async def req_init_qp(self):
        for caseIdx in range(self.qpNum):
            qpInitAttrMask = IBV_QP_STATE + IBV_QP_PKEY_INDEX + IBV_QP_ACCESS_FLAGS

            qpReqType = BitStream(uint = REQ_QP_MODIFY, length = QP_REQTYPE_B)
            qpn = BitStream(uint = self.qpnVec[caseIdx], length = QP_QPN_B)
            qpAttrMask = BitStream(uint = qpInitAttrMask, length = QP_ATTRMASK_B)
            qpReq  = reqQp(qpReqType = qpReqType, qpn = qpn, qpAttrMask = qpAttrMask)
            qpReq.mkSimQpAttr(pmtu_value = IBV_MTU_256, qpState = IBV_QPS_INIT)
            metaData = MetaDataTransaction()
            metaData.tdata = qpReq.getBusValue()
            await self.meta_data_src.send(metaData)

    async def resp_init_qp(self):
        for caseIdx in range(self.qpNum):
            dut_alloc_qp_resp = await self.meta_data_sink.recv()
            metaRespBus = BitStream(uint = dut_alloc_qp_resp.tdata.integer, length = META_DATA_BITS)
            qpResp = respQp(metaRespBus)
            if qpResp.busType.uint != METADATA_QP_T:
                self.log.error(f'Bus type should be {METADATA_QP_T}, instead decoded {qpResp.busType.uint}')
            if not qpResp.successOrNot:
                self.log.error("QP to init state not successfull!")
            if qpResp.qpaQpState.uint != IBV_QPS_INIT:
                self.log.error(f'QP state not in init state, instead decoded {qpResp.qpaQpState.uint}')
            else:
                self.log.info(f'QP {caseIdx} state to Init')

    async def req_rtr_qp(self):
        for caseIdx in range(self.qpNum):
            qpInit2RtrAttrMask = (IBV_QP_STATE + IBV_QP_PATH_MTU + IBV_QP_DEST_QPN +
                                  IBV_QP_RQ_PSN + IBV_QP_MAX_DEST_RD_ATOMIC + IBV_QP_MIN_RNR_TIMER)
            dqpn_value = self.dqpnVec[caseIdx]

            qpReqType = BitStream(uint = REQ_QP_MODIFY, length = QP_REQTYPE_B)
            qpn = BitStream(uint = self.qpnVec[caseIdx], length = QP_QPN_B)
            qpAttrMask = BitStream(uint = qpInit2RtrAttrMask, length = QP_ATTRMASK_B)
            qpReq = reqQp(qpReqType = qpReqType, qpn = qpn, qpAttrMask = qpAttrMask)
            qpReq.mkSimQpAttr(pmtu_value = IBV_MTU_256, dqpn_value = dqpn_value, qpState = IBV_QPS_RTR)
            metaData = MetaDataTransaction()
            metaData.tdata = qpReq.getBusValue()
            await self.meta_data_src.send(metaData)

    async def resp_rtr_qp(self):
        for caseIdx in range(self.qpNum):
            dut_alloc_qp_resp = await self.meta_data_sink.recv()
            metaRespBus = BitStream(uint = dut_alloc_qp_resp.tdata.integer, length = META_DATA_BITS)
            qpResp = respQp(metaRespBus)
            if qpResp.busType.uint != METADATA_QP_T:
                self.log.error(f'Bus type should be {METADATA_QP_T}, instead decoded {qpResp.busType.uint}')
            if not qpResp.successOrNot:
                self.log.error("QP to RTR state not successfull!")
            if qpResp.qpaQpState.uint != IBV_QPS_RTR:
                self.log.error(f'QP state not in rtr state, instead decoded {qpResp.qpaQpState.uint}')
            else:
                self.log.info(f'QP {caseIdx} state to RTR with qpn: {qpResp.qpn.hex} and dqpn: {qpResp.qpaDqpn.hex}')
            self.qpnVec4RTS.append(qpResp.qpn.uint)
            self.sqpnVec4Write.append([qpResp.qpn.uint, qpResp.qpaDqpn.uint])

    async def req_rts_qp(self):
        for caseIdx in range(self.qpNum):
            qpRtr2RtsAttrMask = (IBV_QP_STATE + IBV_QP_SQ_PSN + IBV_QP_TIMEOUT
                                  + IBV_QP_RETRY_CNT + IBV_QP_RNR_RETRY + IBV_QP_MAX_QP_RD_ATOMIC)
            dqpn_value = self.dqpnVec[caseIdx]

            qpn = BitStream(uint = self.qpnVec4RTS[caseIdx], length = QP_QPN_B)
            qpReqType = BitStream(uint = REQ_QP_MODIFY, length = QP_REQTYPE_B)
            qpAttrMask = BitStream(uint = qpRtr2RtsAttrMask, length = QP_ATTRMASK_B)
            qpReq = reqQp(qpReqType = qpReqType, qpn = qpn, qpAttrMask = qpAttrMask)
            qpReq.mkSimQpAttr(pmtu_value = IBV_MTU_256, qpState = IBV_QPS_RTS)
            metaData = MetaDataTransaction()
            metaData.tdata = qpReq.getBusValue()
            await self.meta_data_src.send(metaData)

    async def resp_rts_qp(self):
        for caseIdx in range(self.qpNum):
            dut_alloc_qp_resp = await self.meta_data_sink.recv()
            metaRespBus = BitStream(uint = dut_alloc_qp_resp.tdata.integer, length = META_DATA_BITS)
            qpResp = respQp(metaRespBus)
            if qpResp.busType.uint != METADATA_QP_T:
                self.log.error(f'Bus type should be {METADATA_QP_T}, instead decoded {qpResp.busType.uint}')
            if not qpResp.successOrNot:
                self.log.error("QP to RTS state not successfull!")
            if qpResp.qpaQpState.uint != IBV_QPS_RTS:
                self.log.error(f'QP state not in rts state, instead decoded {qpResp.qpaQpState.uint}')
            else:
                self.log.info(f'QP {caseIdx} state to RTS')

    async def issue_work_req(self):
        for caseIdx in range(self.qpNum):
            qpiType = self.qpiTypeVec[caseIdx]
            sqpn, dqpn = self.sqpnVec4Write[caseIdx]
            lKey = self.lKeyVec4Write[caseIdx]
            rKey = self.rKeyVec[caseIdx]
            lAddr = DEFAULT_ADDR
            rAddr = DEFAULT_ADDR
            wrReq = self.gen_wr(qpiType = qpiType,
                                wrOpCode = IBV_WR_RDMA_WRITE,
                                needResp = False,
                                sqpn = sqpn,
                                dqpn = dqpn,
                                lKey = lKey,
                                rKey = rKey,
                                lAddr = lAddr,
                                rAddr = rAddr,
                                )
            await self.work_req_src.send(wrReq)
            self.log.info(f'WR {caseIdx} has been issued!')

    def gen_wr(self, qpiType, wrOpCode, needResp, sqpn, dqpn, lKey, rKey, lAddr, rAddr):
        isAtomicWR = False
        wrReq = WorkReqTransaction()
        wrReq.id = random.getrandbits(WR_ID_B)
        wrReq.opCode = wrOpCode
        wrReq.flags = IBV_SEND_SIGNALED if needResp else IBV_SEND_NO_FLAGS
        wrReq.raddr = rAddr
        wrReq.rkey = rKey
        wrReq.len = random.randint(MIN_PAYLOAD_LEN, MAX_PAYLOAD_LEN) # different if atomic WR
        wrReq.laddr = lAddr
        wrReq.lkey = lKey
        wrReq.sqpn = sqpn
        wrReq.solicited = 0
        wrReq.comp = tagInvalid()
        wrReq.swap = tagInvalid()
        wrReq.imm_dt = tagInvalid()
        wrReq.rkey_to_inv = tagInvalid()
        wrReq.srqn = tagValid(dqpn, WR_M_SRQN_B) if qpiType == IBV_QPT_XRC_SEND else tagInvalid()
        wrReq.dqpn = tagValid(dqpn, WR_M_DQPN_B) if qpiType == IBV_QPT_UD else tagInvalid()
        wrReq.qkey = tagInvalid()
        return wrReq

    async def get_dma_read_req(self):
        while True:
            dut_dma_req = await self.dma_read_clt_sink.recv()
            await self.dmaRCRespsQ.put(dmaPyServer(initiator = dut_dma_req.initiator.integer,
                                                   sqpn = dut_dma_req.sqpn.integer,
                                                   startAddr = dut_dma_req.start_addr.integer,
                                                   pktLen = dut_dma_req.len.integer,
                                                   wrId = dut_dma_req.wr_id.integer,
                                                   ))
            self.log.debug(f'Received DMA req: wrId -> {hex(dut_dma_req.wr_id.integer)}, len -> {hex(dut_dma_req.len.integer)}')

    async def get_dma_read_resp(self):
        while True:
            dmaRCRespPkts = await self.dmaRCRespsQ.get()
            self.log.debug(f'Sending DMA resp: wrId -> {hex(dmaRCRespPkts[0].wr_id)}')
            for dmaRCRespPkt in dmaRCRespPkts:
                await self.dma_read_clt_src.send(dmaRCRespPkt)

    async def get_axis_data(self):
        count = 0
        while True:
            axis_data = await self.data_stream_sink.recv()
            count = count + 1
            self.log.info(f'Detected AXI-Stream data frame #{count}')

@cocotb.test(timeout_time=1000000000, timeout_unit="ns")
async def runAxisTransportLayerTester(dut):
    tester = AxisTransportLayerTester(
        dut, CASES_NUM, PD_NUM, QP_NUM, MR_NUM
    )
    await tester.gen_clock()
    await tester.gen_reset()
    tester.log.info("Starting DmaPyServer")
    get_dma_req_thread = cocotb.start_soon(tester.get_dma_read_req())
    get_dma_resp_thread = cocotb.start_soon(tester.get_dma_read_resp())
    get_axis_data_thread = cocotb.start_soon(tester.get_axis_data())
    tester.log.info("Start testing!")
    alloc_pd_thread = cocotb.start_soon(tester.req_alloc_pd())
    check_alloc_pd_thread = cocotb.start_soon(tester.resp_alloc_pd())
    await check_alloc_pd_thread
    alloc_mr_thread = cocotb.start_soon(tester.req_alloc_mr())
    check_alloc_mr_thread = cocotb.start_soon(tester.resp_alloc_mr())
    await check_alloc_mr_thread
    create_qp_thread = cocotb.start_soon(tester.req_create_qp())
    check_create_qp_thread = cocotb.start_soon(tester.resp_create_qp())
    await check_create_qp_thread
    init_qp_thread = cocotb.start_soon(tester.req_init_qp())
    check_init_qp_thread = cocotb.start_soon(tester.resp_init_qp())
    await check_init_qp_thread
    rtr_qp_thread = cocotb.start_soon(tester.req_rtr_qp())
    check_rtr_qp_thread = cocotb.start_soon(tester.resp_rtr_qp())
    await check_rtr_qp_thread
    rts_qp_thread = cocotb.start_soon(tester.req_rts_qp())
    check_rts_qp_thread = cocotb.start_soon(tester.resp_rts_qp())
    await check_rts_qp_thread
    issue_wr_thread = cocotb.start_soon(tester.issue_work_req())
    await issue_wr_thread
    for i in range(100):
        await RisingEdge(tester.clock)

def test_AxisTransportLayer():
    toplevel = "mkAxiSTransportLayer"
    module = os.path.splitext(os.path.basename(__file__))[0]
    test_dir = os.path.abspath(os.path.dirname(__file__))
    v_src_dir = os.path.join(test_dir, "../../src/rtl/")
    src_build_dir = os.path.join(test_dir, "../../src/build/")
    sim_build = os.path.join(test_dir, "build")
    v_top_file = os.path.join(test_dir, "verilog", f"{toplevel}.v")
    verilog_sources = [v_top_file]
    cocotb_test.simulator.run(
        toplevel = toplevel,
        module = module,
        verilog_sources = verilog_sources,
        python_search = test_dir,
        sim_build = sim_build,
        timescale = "1ns/1ps",
        waves = 1,
    )

if __name__ == "__main__":
    test_AxisTransportLayer()
