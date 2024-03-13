from cocotbext.axi.stream import define_stream
import random
from bitstring import Bits, BitArray, BitStream, pack
import math

# BSV Settins. These must match in the 'Settings.bsv' source file
MAX_PD = 1

# MetaData fields bits
META_DATA_BITS = 303
METADATA_PD_T = 0
METADATA_MR_T = 1
METADATA_QP_T = 2

# PD
PD_INDEX_B = int(math.log2(MAX_PD))
PD_ALLOC_OR_NOT_B = 1
PD_HANDLER_B = 32
PD_KEY_B = PD_HANDLER_B - PD_INDEX_B

# MR
MR_ALLOC_OR_NOT_B = 1
MR_LADDR_B = 64
MR_LEN_B = 32
MR_ACCFLAGS_B = 8
MR_PDHANDLER_B = 32
MR_LKEYPART_B = 25
MR_RKEYPART_B = 25
MR_LKEYORNOT_B = 1
MR_RKEY_B = 32
MR_LKEY_B = 32

# QP InitAttr
QPI_TYPE_B = 4
QPI_SQSIGALL_B = 1

# QP Attr
QPA_QPSTATE_B = 4
QPA_CURRQPSTATE_B = 4
QPA_PMTU_B = 3
QPA_QKEY_B = 32
QPA_RQPSN_B = 24
QPA_SQPSN_B = 24
QPA_DQPN_B = 24
QPA_QPACCFLAGS_B = 8
QPA_CAP_B = 40
QPA_PKEY_B = 16
QPA_SQDRAINING_B = 1
QPA_MAXREADATOMIC_B = 8
QPA_MAXDESTREADATOMIC_B = 8
QPA_RNRTIMER_B = 5
QPA_TIMEOUT_B = 5
QPA_RETRYCNT_B = 3
QPA_RNRRETRY_B = 3

# QP
QP_REQTYPE_B = 2
QP_PDHANDLER_B = 32
QP_QPN_B = 24
QP_ATTRMASK_B = 26
QP_ATTR_B = 212
QP_QPSTATE_B = 4
QP_INITATTR_B = QPI_TYPE_B + QPI_SQSIGALL_B

# WorkReq fields bits
WR_ID_B = 64
WR_OPCODE_B = 4
WR_FLAGS_B = 5
WR_RADDR_B = 64
WR_RKEY_B = 32
WR_LEN_B = 32
WR_LADDR_B = 64
WR_LKEY_B = 32
WR_SQPN_B = 24
WR_SOLICITED_B = 1
WR_M_COMP_B = 65
WR_M_SWAP_B = 65
WR_M_IMMDT_B = 33
WR_M_RKEY2INV_B = 33
WR_M_SRQN_B = 25
WR_M_DQPN_B = 25
WR_M_QKEY_B = 33

# Dma Field bits
DMA_DS_DATA_B = 256
DMA_DS_BYTEEN_B = int(DMA_DS_DATA_B / 8)
DMA_DS_ISFIRST_B = 1
DMA_DS_ISLAST_B = 1
DMA_INITIATOR_B = 4
DMA_SQPN_B = 24
DMA_WRID_B = 64
DMA_ISRESPERR_B = 1
DMA_DATASTREAM_B = 290

# Enumerate Types
# QpReqType
REQ_QP_CREATE = 0
REQ_QP_DESTROY = 1
REQ_QP_MODIFY = 2
REQ_QP_QUERY = 3

# TypeQP
IBV_QPT_RC = 2
IBV_QPT_UC = 3
IBV_QPT_UD = 4
IBV_QPT_XRC_SEND = 9
IBV_QPT_XRC_RECV = 10

# PMTU
IBV_MTU_256 = 1
IBV_MTU_512 = 2
IBV_MTU_1024 = 3
IBV_MTU_2048 = 4
IBV_MTU_4096 = 5

# QPS
IBV_QPS_RESET = 0
IBV_QPS_INIT = 1
IBV_QPS_RTR = 2
IBV_QPS_RTS = 3
IBV_QPS_SQD = 4
IBV_QPS_SQE = 5
IBV_QPS_ERR = 6
IBV_QPS_UNKNOWN = 7
IBV_QPS_CREATE = 8

# QPAttrMask
IBV_QP_NO_FLAGS            = 0       # Not defined in rdma-core
IBV_QP_STATE               = 1       # 1 << 0
IBV_QP_CUR_STATE           = 2       # 1 << 1
IBV_QP_EN_SQD_ASYNC_NOTIFY = 4       # 1 << 2
IBV_QP_ACCESS_FLAGS        = 8       # 1 << 3
IBV_QP_PKEY_INDEX          = 16      # 1 << 4
IBV_QP_PORT                = 32      # 1 << 5
IBV_QP_QKEY                = 64      # 1 << 6
IBV_QP_AV                  = 128     # 1 << 7
IBV_QP_PATH_MTU            = 256     # 1 << 8
IBV_QP_TIMEOUT             = 512     # 1 << 9
IBV_QP_RETRY_CNT           = 1024    # 1 << 10
IBV_QP_RNR_RETRY           = 2048    # 1 << 11
IBV_QP_RQ_PSN              = 4096    # 1 << 12
IBV_QP_MAX_QP_RD_ATOMIC    = 8192    # 1 << 13
IBV_QP_ALT_PATH            = 16384   # 1 << 14
IBV_QP_MIN_RNR_TIMER       = 32768   # 1 << 15
IBV_QP_SQ_PSN              = 65536   # 1 << 16
IBV_QP_MAX_DEST_RD_ATOMIC  = 131072  # 1 << 17
IBV_QP_PATH_MIG_STATE      = 262144  # 1 << 18
IBV_QP_CAP                 = 524288  # 1 << 19
IBV_QP_DEST_QPN            = 1048576 # 1 << 20
# These bits were supported on older kernels, but never exposed from libibverbs
# _IBV_QP_SMAC               = 1 << 21
# _IBV_QP_ALT_SMAC           = 1 << 22
# _IBV_QP_VID                = 1 << 23
# _IBV_QP_ALT_VID            = 1 << 24
IBV_QP_RATE_LIMIT          = 33554432 # 1 << 25

# WorkReq send flags
IBV_SEND_NO_FLAGS  = 0 # Not defined in rdma-core
IBV_SEND_FENCE     = 1
IBV_SEND_SIGNALED  = 2
IBV_SEND_SOLICITED = 4
IBV_SEND_INLINE    = 8
IBV_SEND_IP_CSUM   = 16

# WorkReqOpCode
IBV_WR_RDMA_WRITE           =  0
IBV_WR_RDMA_WRITE_WITH_IMM  =  1
IBV_WR_SEND                 =  2
IBV_WR_SEND_WITH_IMM        =  3
IBV_WR_RDMA_READ            =  4
IBV_WR_ATOMIC_CMP_AND_SWP   =  5
IBV_WR_ATOMIC_FETCH_AND_ADD =  6
IBV_WR_LOCAL_INV            =  7
IBV_WR_BIND_MW              =  8
IBV_WR_SEND_WITH_INV        =  9
IBV_WR_TSO                  = 10
IBV_WR_DRIVER1              = 11





# Settings
DEFAULT_ADDR = 0
DEFAULT_LEN = 1 << 31
ACC_PERM = 15 # 0x0F => local_write, remote_write, remote_read, remote_atomic
MAX_QP_WR = 32
MAX_QP_RD_ATOM = MAX_QP_WR / 2
MAX_QP_DST_RD_ATOM = MAX_QP_WR / 2
DEFAULT_RETRY_NUM = 3
MIN_PAYLOAD_LEN = 1
MAX_PAYLOAD_LEN = 200

(
    RecvReqBus,
    RecvReqTransaction,
    RecvReqSource,
    RecvReqSink,
    RecvReqMonitor,
) = define_stream(
    "RecvReq",
    signals=[
        "valid",
        "ready",
        "id",
        "len",
        "laddr",
        "lkey",
        "sqpn",
    ],
)

(
    WorkReqBus,
    WorkReqTransaction,
    WorkReqSource,
    WorkReqSink,
    WorkReqMonitor,
) = define_stream(
    "WorkReq",
    signals=[
        "valid",
        "ready",
        "id",
        "op_code",
        "flags",
        "raddr",
        "rkey",
        "len",
        "laddr",
        "lkey",
        "sqpn",
        "solicited",
        "comp",
        "swap",
        "imm_dt",
        "rkey_to_inv",
        "srqn",
        "dqpn",
        "qkey",
    ],
)

(
    MetaDataBus,
    MetaDataTransaction,
    MetaDataSource,
    MetaDataSink,
    MetaDataMonitor,
) = define_stream(
    "MetaData",
    signals=[
        "tvalid",
        "tready",
        "tdata",
    ],
)

(
    WorkCompBus,
    WorkCompTransaction,
    WorkCompSource,
    WorkCompSink,
    WorkCompMonitor,
) = define_stream(
    "WorkComp",
    signals=[
        "valid",
        "ready",
        "id",
        "op_code",
        "flags",
        "status",
        "len",
        "pkey",
        "qpn",
        "imm_dt",
        "rkey_to_inv",
    ],
)

(
    DmaReadCltReqBus,
    DmaReadCltReqTransaction,
    DmaReadCltReqSource,
    DmaReadCltReqSink,
    DmaReadCltReqMonitor,
) = define_stream(
    "DmaReadCltReq",
    signals=[
        "valid",
        "ready",
        "initiator",
        "sqpn",
        "wr_id",
        "start_addr",
        "len",
        "mr_idx",
    ],
)

(
    DmaReadCltRespBus,
    DmaReadCltRespTransaction,
    DmaReadCltRespSource,
    DmaReadCltRespSink,
    DmaReadCltRespMonitor,
) = define_stream(
    "DmaReadCltResp",
    signals=[
        "valid",
        "ready",
        "initiator",
        "sqpn",
        "wr_id",
        "is_resp_err",
        "data_stream",
    ],
)

(
    DmaWriteCltReqBus,
    DmaWriteCltReqTransaction,
    DmaWriteCltReqSource,
    DmaWriteCltReqSink,
    DmaWriteCltReqMonitor,
) = define_stream(
    "DmaWriteCltReq",
    signals=[
        "valid",
        "ready",
        "meta_data",
        "data_stream",
    ],
)

(
    DmaWriteCltRespBus,
    DmaWriteCltRespTransaction,
    DmaWriteCltRespSource,
    DmaWriteCltRespSink,
    DmaWriteCltRespMonitor,
) = define_stream(
    "DmaWriteCltResp",
    signals=[
        "valid",
        "initiator",
        "sqpn",
        "psn",
        "is_resp_err",
    ],
)

# Utility functions
def dontCareVec(length):
    return BitStream(uint = random.getrandbits(length), length = length)

def list_full_paths(directory):
    return [os.path.join(directory, file) for file in os.listdir(directory)]

def slice_vec(a, msb, lsb):
    if lsb == 0:
        return a[-msb-1:]
    else:
        return a[-msb-1:-lsb]

def get_bool(a, pos):
    return a[-pos-1]

# TODO incorporate to class encodeQp
def create_bus(busLength, busType, *argv):
    metaBus = BitStream()
    for arg in argv:
        metaBus.append(arg)
    fullBus = BitStream(busLength - metaBus.length)
    fullBus.append(metaBus)
    fullBus.overwrite(busType, pos=0)
    return fullBus

# TODO incorporate to create_bus
def create_generic_bus(busLength, *argv):
    metaBus = BitStream()
    for arg in argv:
        metaBus.append(arg)
    fullBus = BitStream(busLength - metaBus.length)
    fullBus.append(metaBus)
    return fullBus

def mkSimQpAttr(pmtu_value, qpState=random.getrandbits(QPA_QPSTATE_B), dqpn_value=random.getrandbits(QPA_DQPN_B), setExpectedPsnAsNextPsn = True, setZero2ExpectedPsnAndNextPsn = True):
    epsn_tmp = random.getrandbits(QPA_RQPSN_B)
    npsn_tmp = random.getrandbits(QPA_SQPSN_B)
    if setExpectedPsnAsNextPsn:
        epsn_tmp = npsn_tmp
    if setZero2ExpectedPsnAndNextPsn:
        epsn_tmp = 0
        npsn_tmp = 0
    qpAccessFlags_value = 0x0E # access_remote_write, access_remote_read, access_remote_atomic
    cap_value = 0x2020010100 # line 1145 file Utils4Test.bsv # TODO create single fields

    qpState = BitStream(uint = qpState, length = QPA_QPSTATE_B)
    curQpState = dontCareVec(QPA_CURRQPSTATE_B)
    pmtu = BitStream(uint = pmtu_value, length = QPA_PMTU_B)
    qkey = BitStream (uint = random.getrandbits(QPA_QKEY_B), length=(QPA_QKEY_B))
    rqPsn = BitStream(uint = epsn_tmp, length = QPA_RQPSN_B)
    sqPsn = BitStream(uint = npsn_tmp, length = QPA_SQPSN_B)
    dqpn = BitStream(uint = dqpn_value, length = QPA_DQPN_B)
    qpAccessFlags = BitStream(uint = qpAccessFlags_value, length = QPA_QPACCFLAGS_B)
    cap = BitStream(uint = cap_value, length = QPA_CAP_B)
    pKeyIndex = BitStream(uint = random.getrandbits(QPA_PKEY_B), length = QPA_PKEY_B)
    sqDraining = BitStream(uint = False, length = QPA_SQDRAINING_B)
    maxReadAtomic = BitStream(uint = MAX_QP_RD_ATOM, length = QPA_MAXREADATOMIC_B)
    maxDestReadAtomic = BitStream(uint = MAX_QP_DST_RD_ATOM, length = QPA_MAXDESTREADATOMIC_B)
    minRnrTimer = BitStream(uint = 1, length = QPA_RNRTIMER_B)
    timeOut = BitStream(uint = 1, length = QPA_TIMEOUT_B)
    retryCnt = BitStream(uint = DEFAULT_RETRY_NUM, length = QPA_RETRYCNT_B)
    rnrRetry = BitStream(uint = DEFAULT_RETRY_NUM, length = QPA_RNRRETRY_B)

    fullBus = create_generic_bus(QP_ATTR_B, qpState, curQpState, pmtu, qkey, rqPsn, sqPsn, dqpn, qpAccessFlags, cap, pKeyIndex, sqDraining, maxReadAtomic, maxDestReadAtomic, minRnrTimer, timeOut, retryCnt, rnrRetry)
    return fullBus

def tagValid(data, busWidth):
    return (data | (1 << (busWidth - 1)))

def tagInvalid():
    return 0
