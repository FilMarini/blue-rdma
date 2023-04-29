import ClientServer :: *;
import FIFOF :: *;
import GetPut :: *;
import PAClib :: *;

import Controller :: *;
import DataTypes :: *;
import ExtractAndPrependPipeOut :: *;
import Headers :: *;
import PayloadConAndGen :: *;
import PrimUtils :: *;
import Utils :: *;

function Maybe#(QPN) getMaybeDestQpnSQ(WorkReq wr, Controller cntrl);
    return case (cntrl.getQpType)
        IBV_QPT_RC      ,
        IBV_QPT_UC      ,
        IBV_QPT_XRC_SEND: tagged Valid cntrl.getDQPN;
        IBV_QPT_UD      : wr.dqpn;
        default         : tagged Invalid;
    endcase;
endfunction

function Maybe#(RdmaOpCode) genFirstOrOnlyReqRdmaOpCode(WorkReqOpCode wrOpCode, Bool isOnlyReqPkt);
    return case (wrOpCode)
        IBV_WR_RDMA_WRITE          : tagged Valid (isOnlyReqPkt ? RDMA_WRITE_ONLY                : RDMA_WRITE_FIRST);
        IBV_WR_RDMA_WRITE_WITH_IMM : tagged Valid (isOnlyReqPkt ? RDMA_WRITE_ONLY_WITH_IMMEDIATE : RDMA_WRITE_FIRST);
        IBV_WR_SEND                : tagged Valid (isOnlyReqPkt ? SEND_ONLY                      : SEND_FIRST);
        IBV_WR_SEND_WITH_IMM       : tagged Valid (isOnlyReqPkt ? SEND_ONLY_WITH_IMMEDIATE       : SEND_FIRST);
        IBV_WR_SEND_WITH_INV       : tagged Valid (isOnlyReqPkt ? SEND_ONLY_WITH_INVALIDATE      : SEND_FIRST);
        IBV_WR_RDMA_READ           : tagged Valid RDMA_READ_REQUEST;
        IBV_WR_ATOMIC_CMP_AND_SWP  : tagged Valid COMPARE_SWAP;
        IBV_WR_ATOMIC_FETCH_AND_ADD: tagged Valid FETCH_ADD;
        default                    : tagged Invalid;
    endcase;
endfunction

function Maybe#(RdmaOpCode) genMiddleOrLastReqRdmaOpCode(WorkReqOpCode wrOpCode, Bool isLastReqPkt);
    return case (wrOpCode)
        IBV_WR_RDMA_WRITE         : tagged Valid (isLastReqPkt ? RDMA_WRITE_LAST                : RDMA_WRITE_MIDDLE);
        IBV_WR_RDMA_WRITE_WITH_IMM: tagged Valid (isLastReqPkt ? RDMA_WRITE_LAST_WITH_IMMEDIATE : RDMA_WRITE_MIDDLE);
        IBV_WR_SEND               : tagged Valid (isLastReqPkt ? SEND_LAST                      : SEND_MIDDLE);
        IBV_WR_SEND_WITH_IMM      : tagged Valid (isLastReqPkt ? SEND_LAST_WITH_IMMEDIATE       : SEND_MIDDLE);
        IBV_WR_SEND_WITH_INV      : tagged Valid (isLastReqPkt ? SEND_LAST_WITH_INVALIDATE      : SEND_MIDDLE);
        default                   : tagged Invalid;
    endcase;
endfunction

function Maybe#(XRCETH) genXRCETH(WorkReq wr, Controller cntrl);
    return case (cntrl.getQpType)
        IBV_QPT_XRC_SEND: tagged Valid XRCETH {
            srqn: unwrapMaybe(wr.srqn),
            rsvd: unpack(0)
        };
        default: tagged Invalid;
    endcase;
endfunction

function Maybe#(DETH) genDETH(WorkReq wr, Controller cntrl);
    return case (cntrl.getQpType)
        IBV_QPT_UD: tagged Valid DETH {
            qkey: unwrapMaybe(wr.qkey),
            sqpn: cntrl.getSQPN,
            rsvd: unpack(0)
        };
        default: tagged Invalid;
    endcase;
endfunction

function Maybe#(RETH) genRETH(WorkReq wr);
    return case (wr.opcode)
        IBV_WR_RDMA_WRITE         ,
        IBV_WR_RDMA_WRITE_WITH_IMM,
        IBV_WR_RDMA_READ          : tagged Valid RETH {
            va: wr.raddr,
            rkey: wr.rkey,
            dlen: wr.len
        };
        default                   : tagged Invalid;
    endcase;
endfunction

function Maybe#(AtomicEth) genAtomicEth(WorkReq wr);
    if (wr.swap matches tagged Valid .swap &&& wr.comp matches tagged Valid .comp) begin
        return case (wr.opcode)
            IBV_WR_ATOMIC_CMP_AND_SWP  ,
            IBV_WR_ATOMIC_FETCH_AND_ADD: tagged Valid AtomicEth {
                va: wr.raddr,
                rkey: wr.rkey,
                swap: swap,
                comp: comp
            };
            default                    : tagged Invalid;
        endcase;
    end
    else begin
        return tagged Invalid;
    end
endfunction

function Maybe#(ImmDt) genImmDt(WorkReq wr);
    return case (wr.opcode)
        IBV_WR_RDMA_WRITE_WITH_IMM,
        IBV_WR_SEND_WITH_IMM      : tagged Valid ImmDt {
            data: unwrapMaybe(wr.immDt)
        };
        default                   : tagged Invalid;
    endcase;
endfunction

function Maybe#(IETH) genIETH(WorkReq wr);
    return case (wr.opcode)
        IBV_WR_SEND_WITH_INV: tagged Valid IETH {
            rkey: unwrapMaybe(wr.rkey2Inv)
        };
        default             : tagged Invalid;
    endcase;
endfunction

function Maybe#(Tuple3#(HeaderData, HeaderByteNum, Bool)) genFirstOrOnlyReqHeader(
    WorkReq wr, Controller cntrl, PSN psn, Bool isOnlyReqPkt
);
    let maybeTrans  = qpType2TransType(cntrl.getQpType);
    let maybeOpCode = genFirstOrOnlyReqRdmaOpCode(wr.opcode, isOnlyReqPkt);
    let maybeDQPN   = getMaybeDestQpnSQ(wr, cntrl);

    let isReadOrAtomicWR = isReadOrAtomicWorkReq(wr.opcode);
    if (
        maybeTrans  matches tagged Valid .trans  &&&
        maybeOpCode matches tagged Valid .opcode &&&
        maybeDQPN   matches tagged Valid .dqpn
    ) begin
        let bth = BTH {
            trans    : trans,
            opcode   : opcode,
            solicited: wr.solicited,
            migReq   : unpack(0),
            padCnt   : (isOnlyReqPkt && !isReadOrAtomicWR) ? calcPadCnt(wr.len) : 0,
            tver     : unpack(0),
            pkey     : cntrl.getPKEY,
            fecn     : unpack(0),
            becn     : unpack(0),
            resv6    : unpack(0),
            dqpn     : dqpn,
            ackReq   : cntrl.getSigAll || (isOnlyReqPkt && workReqRequireAck(wr)),
            resv7    : unpack(0),
            psn      : psn
        };

        let xrceth = genXRCETH(wr, cntrl);
        let deth = genDETH(wr, cntrl);
        let reth = genRETH(wr);
        let atomicEth = genAtomicEth(wr);
        let immDt = genImmDt(wr);
        let ieth = genIETH(wr);

        // If WR has zero length, then no payload, no matter what kind of opcode
        let hasPayload = workReqHasPayload(wr);
        case (wr.opcode)
            IBV_WR_RDMA_WRITE: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC,
                    IBV_QPT_UC: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(reth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(reth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_RDMA_WRITE_WITH_IMM: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC,
                    IBV_QPT_UC: tagged Valid tuple3(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(reth)), pack(unwrapMaybe(immDt))}) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(reth))}),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(reth)), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(reth)) }),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC,
                    IBV_QPT_UC: tagged Valid tuple3(
                        zeroExtendLSB(pack(bth)),
                        fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_UD: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(deth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(DETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND_WITH_IMM: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC,
                    IBV_QPT_UC: tagged Valid tuple3(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB(pack(bth)),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_UD: tagged Valid tuple3(
                        // UD always has only pkt
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(deth)), pack(unwrapMaybe(immDt)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(DETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND_WITH_INV: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid tuple3(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(ieth)) }) :
                            zeroExtendLSB(pack(bth)),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IETH_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(ieth)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IETH_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_RDMA_READ: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(reth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        False // Read requests have no payload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(reth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        False // Read requests have no payload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_ATOMIC_CMP_AND_SWP  ,
            IBV_WR_ATOMIC_FETCH_AND_ADD: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(atomicEth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(ATOMIC_ETH_BYTE_WIDTH)),
                        False // Atomic requests have no payload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(atomicEth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(ATOMIC_ETH_BYTE_WIDTH)),
                        False // Atomic requests have no payload
                    );
                    default: tagged Invalid;
                endcase;
            end
            default: return tagged Invalid;
        endcase
    end
    else begin
        return tagged Invalid;
    end
endfunction

function Maybe#(Tuple3#(HeaderData, HeaderByteNum, Bool)) genMiddleOrLastReqHeader(
    WorkReq wr, Controller cntrl, PSN psn, Bool isLastReqPkt
);
    let maybeTrans  = qpType2TransType(cntrl.getQpType);
    let maybeOpCode = genMiddleOrLastReqRdmaOpCode(wr.opcode, isLastReqPkt);
    let maybeDQPN   = getMaybeDestQpnSQ(wr, cntrl);

    if (
        maybeTrans  matches tagged Valid .trans  &&&
        maybeOpCode matches tagged Valid .opcode &&&
        maybeDQPN   matches tagged Valid .dqpn
    ) begin
        let bth = BTH {
            trans    : trans,
            opcode   : opcode,
            solicited: wr.solicited,
            migReq   : unpack(0),
            padCnt   : isLastReqPkt ? calcPadCnt(wr.len) : 0,
            tver     : unpack(0),
            pkey     : cntrl.getPKEY,
            fecn     : unpack(0),
            becn     : unpack(0),
            resv6    : unpack(0),
            dqpn     : dqpn,
            ackReq   : cntrl.getSigAll || (isLastReqPkt && workReqRequireAck(wr)),
            resv7    : unpack(0),
            psn      : psn
        };

        let xrceth = genXRCETH(wr, cntrl);
        let immDt = genImmDt(wr);
        let ieth = genIETH(wr);

        let hasPayload = True;
        case (wr.opcode)
            IBV_WR_RDMA_WRITE:begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid tuple3(
                        zeroExtendLSB(pack(bth)),
                        fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_RDMA_WRITE_WITH_IMM: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid tuple3(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(immDt))}) :
                            zeroExtendLSB(pack(bth)),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid tuple3(
                        zeroExtendLSB(pack(bth)),
                        fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND_WITH_IMM: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid tuple3(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB(pack(bth)),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND_WITH_INV: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid tuple3(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(ieth)) }) :
                            zeroExtendLSB(pack(bth)),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IETH_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid tuple3(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(ieth)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IETH_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            default: return tagged Invalid;
        endcase
    end
    else begin
        return tagged Invalid;
    end
endfunction
/*
function Maybe#(RdmaHeader) genFirstOrOnlyReqHeader(WorkReq wr, Controller cntrl, PSN psn, Bool isOnlyReqPkt);
    let maybeTrans  = qpType2TransType(cntrl.getQpType);
    let maybeOpCode = genFirstOrOnlyReqRdmaOpCode(wr.opcode, isOnlyReqPkt);
    let maybeDQPN   = getMaybeDestQpnSQ(wr, cntrl);

    let isReadOrAtomicWR = isReadOrAtomicWorkReq(wr.opcode);
    if (
        maybeTrans  matches tagged Valid .trans  &&&
        maybeOpCode matches tagged Valid .opcode &&&
        maybeDQPN   matches tagged Valid .dqpn
    ) begin
        let bth = BTH {
            trans    : trans,
            opcode   : opcode,
            solicited: wr.solicited,
            migReq   : unpack(0),
            padCnt   : (isOnlyReqPkt && !isReadOrAtomicWR) ? calcPadCnt(wr.len) : 0,
            tver     : unpack(0),
            pkey     : cntrl.getPKEY,
            fecn     : unpack(0),
            becn     : unpack(0),
            resv6    : unpack(0),
            dqpn     : dqpn,
            ackReq   : cntrl.getSigAll || (isOnlyReqPkt && workReqRequireAck(wr)),
            resv7    : unpack(0),
            psn      : psn
        };

        let xrceth = genXRCETH(wr, cntrl);
        let deth = genDETH(wr, cntrl);
        let reth = genRETH(wr);
        let atomicEth = genAtomicEth(wr);
        let immDt = genImmDt(wr);
        let ieth = genIETH(wr);

        // If WR has zero length, then no payload, no matter what kind of opcode
        let hasPayload = workReqHasPayload(wr);
        case (wr.opcode)
            IBV_WR_RDMA_WRITE: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC,
                    IBV_QPT_UC: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(reth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(reth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_RDMA_WRITE_WITH_IMM: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC,
                    IBV_QPT_UC: tagged Valid genRdmaHeader(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(reth)), pack(unwrapMaybe(immDt))}) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(reth))}),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(reth)), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(reth)) }),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC,
                    IBV_QPT_UC: tagged Valid genRdmaHeader(
                        zeroExtendLSB(pack(bth)),
                        fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_UD: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(deth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(DETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND_WITH_IMM: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC,
                    IBV_QPT_UC: tagged Valid genRdmaHeader(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB(pack(bth)),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_UD: tagged Valid genRdmaHeader(
                        // UD always has only pkt
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(deth)), pack(unwrapMaybe(immDt)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(DETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND_WITH_INV: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid genRdmaHeader(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(ieth)) }) :
                            zeroExtendLSB(pack(bth)),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IETH_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        isOnlyReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(ieth)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isOnlyReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IETH_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_RDMA_READ: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(reth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        False // Read requests have no payload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(reth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(RETH_BYTE_WIDTH)),
                        False // Read requests have no payload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_ATOMIC_CMP_AND_SWP  ,
            IBV_WR_ATOMIC_FETCH_AND_ADD: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(atomicEth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(ATOMIC_ETH_BYTE_WIDTH)),
                        False // Atomic requests have no payload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(atomicEth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(ATOMIC_ETH_BYTE_WIDTH)),
                        False // Atomic requests have no payload
                    );
                    default: tagged Invalid;
                endcase;
            end
            default: return tagged Invalid;
        endcase
    end
    else begin
        return tagged Invalid;
    end
endfunction

function Maybe#(RdmaHeader) genMiddleOrLastReqHeader(WorkReq wr, Controller cntrl, PSN psn, Bool isLastReqPkt);
    let maybeTrans  = qpType2TransType(cntrl.getQpType);
    let maybeOpCode = genMiddleOrLastReqRdmaOpCode(wr.opcode, isLastReqPkt);
    let maybeDQPN   = getMaybeDestQpnSQ(wr, cntrl);

    if (
        maybeTrans  matches tagged Valid .trans  &&&
        maybeOpCode matches tagged Valid .opcode &&&
        maybeDQPN   matches tagged Valid .dqpn
    ) begin
        let bth = BTH {
            trans    : trans,
            opcode   : opcode,
            solicited: wr.solicited,
            migReq   : unpack(0),
            padCnt   : isLastReqPkt ? calcPadCnt(wr.len) : 0,
            tver     : unpack(0),
            pkey     : cntrl.getPKEY,
            fecn     : unpack(0),
            becn     : unpack(0),
            resv6    : unpack(0),
            dqpn     : dqpn,
            ackReq   : cntrl.getSigAll || (isLastReqPkt && workReqRequireAck(wr)),
            resv7    : unpack(0),
            psn      : psn
        };

        let xrceth = genXRCETH(wr, cntrl);
        let immDt = genImmDt(wr);
        let ieth = genIETH(wr);

        let hasPayload = True;
        case (wr.opcode)
            IBV_WR_RDMA_WRITE:begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid genRdmaHeader(
                        zeroExtendLSB(pack(bth)),
                        fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_RDMA_WRITE_WITH_IMM: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid genRdmaHeader(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(immDt))}) :
                            zeroExtendLSB(pack(bth)),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid genRdmaHeader(
                        zeroExtendLSB(pack(bth)),
                        fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND_WITH_IMM: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid genRdmaHeader(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB(pack(bth)),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(immDt)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IMM_DT_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            IBV_WR_SEND_WITH_INV: begin
                return case (cntrl.getQpType)
                    IBV_QPT_RC: tagged Valid genRdmaHeader(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(ieth)) }) :
                            zeroExtendLSB(pack(bth)),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(IETH_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH)),
                        hasPayload
                    );
                    IBV_QPT_XRC_SEND: tagged Valid genRdmaHeader(
                        isLastReqPkt ?
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)), pack(unwrapMaybe(ieth)) }) :
                            zeroExtendLSB({ pack(bth), pack(unwrapMaybe(xrceth)) }),
                        isLastReqPkt ?
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH) + valueOf(IETH_BYTE_WIDTH)) :
                            fromInteger(valueOf(BTH_BYTE_WIDTH) + valueOf(XRCETH_BYTE_WIDTH)),
                        hasPayload
                    );
                    default: tagged Invalid;
                endcase;
            end
            default: return tagged Invalid;
        endcase
    end
    else begin
        return tagged Invalid;
    end
endfunction
*/
typedef struct {
    PSN            curPSN;
    PendingWorkReq pendingWR;
    Bool           isFirstReqPkt;
    Bool           isLastReqPkt;
} ReqPktHeaderInfo deriving(Bits);

typedef struct {
    Bool isNewWorkReq;
    Bool isZeroPmtuResidue;
    Bool isReliableConnection;
} WorkReqInfo deriving(Bits);

interface ReqGenSQ;
    interface PipeOut#(PendingWorkReq) pendingWorkReqPipeOut;
    interface DataStreamPipeOut rdmaReqDataStreamPipeOut;
    interface PipeOut#(WorkCompGenReqSQ) workCompGenReqPipeOut;
endinterface

module mkReqGenSQ#(
    Controller cntrl,
    DmaReadSrv dmaReadSrv,
    PipeOut#(PendingWorkReq) pendingWorkReqPipeIn,
    Bool pendingWorkReqBufNotEmpty
)(ReqGenSQ);
    // Output FIFO for PipeOut
    FIFOF#(PendingWorkReq)   pendingWorkReqOutQ <- mkFIFOF;
    FIFOF#(WorkCompGenReqSQ) workCompGenReqOutQ <- mkFIFOF;

    // Pipeline FIFO
    FIFOF#(PayloadGenReq) payloadGenReqOutQ <- mkFIFOF;
    FIFOF#(Tuple5#(
        PendingWorkReq, PktNum, PmtuResidue, Bool, Bool
    )) workReqPayloadGenQ <- mkFIFOF;
    FIFOF#(Tuple3#(PendingWorkReq, PktNum, WorkReqInfo)) workReqPktNumQ <- mkFIFOF;
    FIFOF#(Tuple2#(PendingWorkReq, WorkReqInfo))            workReqPsnQ <- mkFIFOF;
    FIFOF#(Tuple2#(PendingWorkReq, WorkReqInfo))            workReqOutQ <- mkFIFOF;
    FIFOF#(PendingWorkReq)                                    reqCountQ <- mkFIFOF;
    FIFOF#(ReqPktHeaderInfo)                          reqHeaderPrepareQ <- mkFIFOF;
    FIFOF#(Tuple3#(
        PendingWorkReq, Maybe#(Tuple3#(HeaderData, HeaderByteNum, Bool)), PSN
    )) pendingReqHeaderQ <- mkFIFOF;
    FIFOF#(Tuple4#(
        PendingWorkReq, Maybe#(RdmaHeader), Maybe#(PayloadGenResp), PSN
    )) reqHeaderGenQ <- mkFIFOF;
    FIFOF#(RdmaHeader)  reqHeaderOutQ <- mkFIFOF;

    function Action flushInternalNormalStatePipelineQ();
        action
            workReqPktNumQ.clear;
            workReqPsnQ.clear;
            workReqOutQ.clear;
            reqCountQ.clear;
            reqHeaderPrepareQ.clear;
            pendingReqHeaderQ.clear;
            reqHeaderGenQ.clear;
            reqHeaderOutQ.clear;
        endaction
    endfunction

    Reg#(PktNum)   remainingPktNumReg <- mkRegU;
    Reg#(PSN)               curPsnReg <- mkRegU;
    Reg#(Bool)       isNormalStateReg <- mkReg(True);
    Reg#(Bool) isFirstOrOnlyReqPktReg <- mkReg(True);

    (* no_implicit_conditions, fire_when_enabled *)
    rule resetAndClear if (cntrl.isReset);
        // Flush output FIFO
        pendingWorkReqOutQ.clear;
        workCompGenReqOutQ.clear;

        // Flush pipeline FIFO
        payloadGenReqOutQ.clear;
        workReqPayloadGenQ.clear;
        flushInternalNormalStatePipelineQ;

        isNormalStateReg       <= True;
        isFirstOrOnlyReqPktReg <= True;

        // $display("time=%0t: reset and clear retry handler", $time);
    endrule

    let payloadGenerator <- mkPayloadGenerator(
        cntrl, dmaReadSrv, convertFifo2PipeOut(payloadGenReqOutQ)
    );

    // Generate header DataStream
    let headerDataStreamAndMetaDataPipeOut <- mkHeader2DataStream(
        convertFifo2PipeOut(reqHeaderOutQ)
    );
    // Prepend header to payload if any
    let rdmaReqPipeOut <- mkPrependHeader2PipeOut(
        headerDataStreamAndMetaDataPipeOut.headerDataStream,
        headerDataStreamAndMetaDataPipeOut.headerMetaData,
        payloadGenerator.payloadDataStreamPipeOut
    );

    (* conflict_free = "deqWorkReqPipeOut, \
                        issuePayloadGenReq, \
                        calcPktNum4NewWorkReq, \
                        calcPktSeqNum4NewWorkReq, \
                        outputNewPendingWorkReq, \
                        countReqPkt, \
                        prepareReqHeaderGen, \
                        genReqHeader, \
                        recvPayloadGenRespAndGenErrWorkComp, \
                        errFlushWR, \
                        errFlushPipelineQ" *)
    rule deqWorkReqPipeOut;
        let qpType = cntrl.getQpType;
        immAssert(
            qpType == IBV_QPT_RC || qpType == IBV_QPT_UC ||
            qpType == IBV_QPT_XRC_SEND || qpType == IBV_QPT_UD,
            "qpType assertion @ mkReqGenSQ",
            $format(
                "qpType=", fshow(qpType), " unsupported"
            )
        );

        let isReliableConnection = qpType == IBV_QPT_RC || qpType == IBV_QPT_XRC_SEND;
        if (cntrl.isSQD) begin
            immAssert(
                isReliableConnection,
                "SQD assertion @ mkReqGenSQ",
                $format(
                    "cntrl.isSQD=", fshow(cntrl.isSQD),
                    " should be RC or XRC, but qpType=", fshow(qpType)
                )
            );
        end
/*
        let shouldDeqPendingWR = False;
        let curPendingWR = pendingWorkReqPipeIn.first;
        if (
            cntrl.isSQD || // SQ Drain
            (cntrl.isRTS && containWorkReqFlag(curPendingWR.wr.flags, IBV_SEND_FENCE)) // Fence
        ) begin
            if (pendingWorkReqBufNotEmpty) begin
                $info(
                    "time=%0t: wait pendingWorkReqBufNotEmpty=",
                    $time, fshow(pendingWorkReqBufNotEmpty),
                    " to be false, when IBV_QPS_SQD or IBV_SEND_FENCE"
                );
            end
            else begin
                shouldDeqPendingWR = True;
            end
        end
        else begin
            shouldDeqPendingWR = True;
        end
*/
        let shouldDeqPendingWR = True;
        let curPendingWR = pendingWorkReqPipeIn.first;
        if (
            cntrl.isRTS && containWorkReqFlag(curPendingWR.wr.flags, IBV_SEND_FENCE) // Fence
        ) begin
            shouldDeqPendingWR = !pendingWorkReqBufNotEmpty;
            $info(
                "time=%0t: wait pendingWorkReqBufNotEmpty=",
                $time, fshow(pendingWorkReqBufNotEmpty),
                " to be false, when IBV_QPS_SQD or IBV_SEND_FENCE"
            );
        end
        else begin // SQ Drain
            shouldDeqPendingWR = !cntrl.isSQD;
        end

        immAssert(
            curPendingWR.wr.sqpn == cntrl.getSQPN,
            "curPendingWR.wr.sqpn assertion @ mkWorkReq2RdmaReq",
            $format(
                "curPendingWR.wr.sqpn=%h should == cntrl.getSQPN=%h",
                curPendingWR.wr.sqpn, cntrl.getSQPN
            )
        );

        if (isAtomicWorkReq(curPendingWR.wr.opcode)) begin
            immAssert(
                curPendingWR.wr.len == fromInteger(valueOf(ATOMIC_WORK_REQ_LEN)),
                "curPendingWR.wr.len assertion @ mkWorkReq2RdmaReq",
                $format(
                    "curPendingWR.wr.len=%0d should be %0d for atomic WR=",
                    curPendingWR.wr.len, valueOf(ATOMIC_WORK_REQ_LEN), fshow(curPendingWR)
                )
            );
        end
        // TODO: handle pending read/atomic request number limit

        let isNewWorkReq = !isValid(curPendingWR.isOnlyReqPkt);
        let { totalReqPktNum, pmtuResidue } = truncateLenByPMTU(curPendingWR.wr.len, cntrl.getPMTU);
        if (shouldDeqPendingWR) begin
            pendingWorkReqPipeIn.deq;

            workReqPayloadGenQ.enq(tuple5(
                curPendingWR, totalReqPktNum, pmtuResidue, isNewWorkReq, isReliableConnection
            ));
            // $display("time=%0t: received PendingWorkReq=", $time, fshow(curPendingWR));
        end
    endrule

    rule issuePayloadGenReq if (cntrl.isRTS && isNormalStateReg);
        let {
            curPendingWR, totalReqPktNum, pmtuResidue, isNewWorkReq, isReliableConnection
        } = workReqPayloadGenQ.first;
        workReqPayloadGenQ.deq;

        if (workReqNeedDmaReadSQ(curPendingWR.wr)) begin
            let payloadGenReq = PayloadGenReq {
                addPadding   : True,
                segment      : True,
                pmtu         : cntrl.getPMTU,
                dmaReadReq   : DmaReadReq {
                    initiator: DMA_INIT_SQ_RD,
                    sqpn     : cntrl.getSQPN,
                    startAddr: curPendingWR.wr.laddr,
                    len      : curPendingWR.wr.len,
                    wrID     : curPendingWR.wr.id
                }
            };
            payloadGenReqOutQ.enq(payloadGenReq);
        end

        let isZeroPmtuResidue = isZero(pmtuResidue);
        let workReqInfo = WorkReqInfo {
            isNewWorkReq        : isNewWorkReq,
            isZeroPmtuResidue   : isZeroPmtuResidue,
            isReliableConnection: isReliableConnection
        };
        workReqPktNumQ.enq(tuple3(curPendingWR, totalReqPktNum, workReqInfo));
    endrule

    rule calcPktNum4NewWorkReq if (cntrl.isRTS && isNormalStateReg);
        let { curPendingWR, totalReqPktNum, workReqInfo } = workReqPktNumQ.first;
        workReqPktNumQ.deq;

        let isZeroPmtuResidue = workReqInfo.isZeroPmtuResidue;
        let isNewWorkReq      = workReqInfo.isNewWorkReq;

        if (isNewWorkReq) begin
            // let { isOnlyPkt, totalPktNum } = calcPktNumByLength(curPendingWR.wr.len, cntrl.getPMTU);
            let totalPktNum = isZeroPmtuResidue ? totalReqPktNum : totalReqPktNum + 1;
            let isOnlyPkt = isLessOrEqOne(totalPktNum);

            curPendingWR.pktNum = tagged Valid totalPktNum;
            curPendingWR.isOnlyReqPkt = tagged Valid isOnlyPkt;
        end
        else begin
            // Should be retry WorkReq
            immAssert(
                isValid(curPendingWR.startPSN) &&
                isValid(curPendingWR.endPSN)   &&
                isValid(curPendingWR.pktNum)   &&
                isValid(curPendingWR.isOnlyReqPkt),
                "curPendingWR assertion @ mkWorkReq2Headers",
                $format(
                    "curPendingWR should have valid PSN and PktNum, curPendingWR=",
                    fshow(curPendingWR)
                )
            );
        end

        workReqPsnQ.enq(tuple2(curPendingWR, workReqInfo));
    endrule

    rule calcPktSeqNum4NewWorkReq if (cntrl.isRTS && isNormalStateReg);
        let { curPendingWR, workReqInfo } = workReqPsnQ.first;
        workReqPsnQ.deq;

        let isNewWorkReq = workReqInfo.isNewWorkReq;
        let totalPktNum  = unwrapMaybe(curPendingWR.pktNum);
        let isOnlyPkt    = unwrapMaybe(curPendingWR.isOnlyReqPkt);

        if (isNewWorkReq) begin
            let startPktSeqNum = cntrl.getNPSN;
            let { nextPktSeqNum, endPktSeqNum } = calcNextAndEndPSN(
                startPktSeqNum, totalPktNum, isOnlyPkt, cntrl.getPMTU
            );
            immAssert(
                endPktSeqNum >= startPktSeqNum && (endPktSeqNum + 1 == nextPktSeqNum),
                "startPSN, endPSN, nextPSN assertion @ mkReqGenSQ",
                $format(
                    "endPSN=%h should >= startPSN=%h, and endPSN=%h + 1 should == nextPSN=%h",
                    endPktSeqNum, startPktSeqNum, endPktSeqNum, nextPktSeqNum
                )
            );

            cntrl.setNPSN(nextPktSeqNum);
            let hasOnlyReqPkt = isOnlyPkt || isReadWorkReq(curPendingWR.wr.opcode);

            curPendingWR.startPSN = tagged Valid startPktSeqNum;
            curPendingWR.endPSN = tagged Valid endPktSeqNum;
            // curPendingWR.pktNum = tagged Valid totalPktNum;
            curPendingWR.isOnlyReqPkt = tagged Valid hasOnlyReqPkt;

            // $display(
            //     "time=%0t: curPendingWR=", $time, fshow(curPendingWR), ", nPSN=%h", nextPktSeqNum
            // );
        end

        workReqOutQ.enq(tuple2(curPendingWR, workReqInfo));
    endrule

    rule outputNewPendingWorkReq if (cntrl.isRTS && isNormalStateReg);
        let { curPendingWR, workReqInfo } = workReqOutQ.first;
        workReqOutQ.deq;

        let qpType         = cntrl.getQpType;
        let isOnlyReqPkt   = unwrapMaybe(curPendingWR.isOnlyReqPkt);
        let isValidWorkReq = !(qpType == IBV_QPT_UD) || isOnlyReqPkt;

        let isNewWorkReq         = workReqInfo.isNewWorkReq;
        let isReliableConnection = workReqInfo.isReliableConnection;
        if (isNewWorkReq) begin
            // let hasOnlyReqPkt = isOnlyPkt || isReadWorkReq(curPendingWR.wr.opcode);

            // curPendingWR.startPSN = tagged Valid startPktSeqNum;
            // curPendingWR.endPSN = tagged Valid endPktSeqNum;
            // curPendingWR.pktNum = tagged Valid totalPktNum;
            // curPendingWR.isOnlyReqPkt = tagged Valid hasOnlyReqPkt;

            // isValidWorkReq = qpType == IBV_QPT_UD ? isOnlyReqPkt : True;

            // Only for RC and XRC output new WR as pending WR, not retry WR
            if (isReliableConnection) begin
                pendingWorkReqOutQ.enq(curPendingWR);
            end
        end
        else begin
            immAssert(
                isValidWorkReq,
                "existing UD WR assertion @ mkReqGenSQ",
                $format(
                    "illegal existing UD WR with length=%0d", curPendingWR.wr.len,
                    " larger than PMTU when QpType=", fshow(qpType),
                    " and isOnlyReqPkt=", fshow(isOnlyReqPkt)
                )
            );
        end

        if (isValidWorkReq) begin // Discard UD with payload more than one packets
            reqCountQ.enq(curPendingWR);
        end
    endrule

    rule countReqPkt if (cntrl.isRTS && isNormalStateReg);
        let pendingWR = reqCountQ.first;

        let startPSN = unwrapMaybe(pendingWR.startPSN);
        let totalPktNum = unwrapMaybe(pendingWR.pktNum);
        let isOnlyReqPkt = unwrapMaybe(pendingWR.isOnlyReqPkt);
        let qpType = cntrl.getQpType;

        let curPSN = curPsnReg;
        let remainingPktNum = remainingPktNumReg;

        let isLastOrOnlyReqPkt = isOnlyReqPkt || (!isFirstOrOnlyReqPktReg && isZero(remainingPktNumReg));
        let isFirstReqPkt = isFirstOrOnlyReqPktReg;
        let isLastReqPkt  = isLastOrOnlyReqPkt;

        // Check WR length cannot be larger than PMTU for UD
        immAssert(
            !(qpType == IBV_QPT_UD) || isOnlyReqPkt,
            "UD assertion @ mkReqGenSQ",
            $format(
                "illegal UD WR with length=%0d", pendingWR.wr.len,
                " larger than PMTU when QpType=", fshow(qpType),
                " and isOnlyReqPkt=", fshow(isOnlyReqPkt)
            )
        );

        if (isLastOrOnlyReqPkt) begin
            reqCountQ.deq;
            isFirstOrOnlyReqPktReg <= True;
        end
        else begin
            isFirstOrOnlyReqPktReg <= False;
        end

        if (isFirstOrOnlyReqPktReg) begin
            curPSN = startPSN;

            // Current cycle output first/only packet,
            // so the remaining pktNum = totalPktNum - 2
            if (isOnlyReqPkt) begin
                remainingPktNum = 0;
            end
            else begin
                remainingPktNum = totalPktNum - 2;
            end
            remainingPktNumReg <= remainingPktNum;
        end
        else if (!isLastReqPkt) begin
            remainingPktNumReg <= remainingPktNum - 1;
        end
        curPsnReg <= curPSN + 1;

        let reqPktHeaderInfo = ReqPktHeaderInfo {
            curPSN       : curPSN,
            pendingWR    : pendingWR,
            isFirstReqPkt: isFirstReqPkt,
            isLastReqPkt : isLastReqPkt
        };
        reqHeaderPrepareQ.enq(reqPktHeaderInfo);
    endrule

    rule prepareReqHeaderGen if (cntrl.isRTS && isNormalStateReg);
        let reqPktHeaderInfo = reqHeaderPrepareQ.first;
        reqHeaderPrepareQ.deq;

        let pendingWR    = reqPktHeaderInfo.pendingWR;
        let curPSN       = reqPktHeaderInfo.curPSN;
        let isOnlyReqPkt = unwrapMaybe(pendingWR.isOnlyReqPkt);
        let isLastReqPkt = reqPktHeaderInfo.isLastReqPkt;
        let maybeReqHeaderGenInfo  = dontCareValue;

        if (reqPktHeaderInfo.isFirstReqPkt) begin
            let maybeFirstOrOnlyHeaderGenInfo = genFirstOrOnlyReqHeader(
                pendingWR.wr, cntrl, curPSN, isOnlyReqPkt
            );
            // TODO: remove this assertion, just report error by WC
            immAssert(
                isValid(maybeFirstOrOnlyHeaderGenInfo),
                "maybeFirstOrOnlyHeaderGenInfo assertion @ mkReqGenSQ",
                $format(
                    "maybeFirstOrOnlyHeaderGenInfo=", fshow(maybeFirstOrOnlyHeaderGenInfo),
                    " is not valid, and current WR=", fshow(pendingWR.wr)
                )
            );

            maybeReqHeaderGenInfo = maybeFirstOrOnlyHeaderGenInfo;
        end
        else begin
            let maybeMiddleOrLastHeaderGenInfo = genMiddleOrLastReqHeader(
                pendingWR.wr, cntrl, curPSN, isLastReqPkt
            );
            immAssert(
                isValid(maybeMiddleOrLastHeaderGenInfo),
                "maybeMiddleOrLastHeaderGenInfo assertion @ mkReqGenSQ",
                $format(
                    "maybeMiddleOrLastHeaderGenInfo=", fshow(maybeMiddleOrLastHeaderGenInfo),
                    " is not valid, and current WR=", fshow(pendingWR.wr)
                )
            );

            maybeReqHeaderGenInfo = maybeMiddleOrLastHeaderGenInfo;

            if (isLastReqPkt) begin
                let endPSN = unwrapMaybe(pendingWR.endPSN);
                immAssert(
                    curPSN == endPSN,
                    "endPSN assertion @ mkWorkReq2Headers",
                    $format(
                        "curPSN=%h should == pendingWR.endPSN=%h",
                        curPSN, endPSN,
                        ", pendingWR=", fshow(pendingWR)
                    )
                );
            end
        end

        pendingReqHeaderQ.enq(tuple3(pendingWR, maybeReqHeaderGenInfo, curPSN));
        // $display(
        //     "time=%0t: output PendingWorkReq=", $time, fshow(pendingWR),
        //     ", maybeReqHeaderGenInfo=", fshow(maybeReqHeaderGenInfo),
        //     ", isOnlyReqPkt=", fshow(isOnlyReqPkt),
        //     ", isLastReqPkt=", fshow(isLastReqPkt),
        //     ", curPSN=%h", curPSN
        // );
    endrule

    rule genReqHeader if (cntrl.isRTS && isNormalStateReg);
        let { pendingWR, maybeReqHeaderGenInfo, triggerPSN } = pendingReqHeaderQ.first;
        pendingReqHeaderQ.deq;

        let maybeReqHeader = tagged Invalid;
        let maybePayloadGenResp = tagged Invalid;
        if (maybeReqHeaderGenInfo matches tagged Valid .reqHeaderGenInfo) begin
            let { headerData, headerLen, hasPayload } = reqHeaderGenInfo;
            let reqHeader = genRdmaHeader(headerData, headerLen, hasPayload);
            maybeReqHeader = tagged Valid reqHeader;

            if (workReqNeedDmaReadSQ(pendingWR.wr)) begin
                let payloadGenResp = payloadGenerator.respPipeOut.first;
                payloadGenerator.respPipeOut.deq;
                maybePayloadGenResp = tagged Valid payloadGenResp;
            end
        end
        reqHeaderGenQ.enq(tuple4(pendingWR, maybeReqHeader, maybePayloadGenResp, triggerPSN));
    endrule

    rule recvPayloadGenRespAndGenErrWorkComp if (cntrl.isRTS && isNormalStateReg);
        let {
            pendingWR, maybeReqHeader, maybePayloadGenResp, triggerPSN
        } = reqHeaderGenQ.first;
        reqHeaderGenQ.deq;

        // Partial WR ACK because this WR has inserted into pending WR buffer.
        let wcReqType         = WC_REQ_TYPE_PARTIAL_ACK;
        let wcStatus          = IBV_WC_LOC_QP_OP_ERR;
        let wcWaitDmaResp     = False;
        let errWorkCompGenReq = WorkCompGenReqSQ {
            wr           : pendingWR.wr,
            wcWaitDmaResp: wcWaitDmaResp,
            wcReqType    : wcReqType,
            triggerPSN   : triggerPSN,
            wcStatus     : wcStatus
        };

        if (maybeReqHeader matches tagged Valid .reqHeader) begin
            if (maybePayloadGenResp matches tagged Valid .payloadGenResp) begin
                if (payloadGenResp.isRespErr) begin
                    workCompGenReqOutQ.enq(errWorkCompGenReq);
                    isNormalStateReg <= False;
                end
                else begin
                    reqHeaderOutQ.enq(reqHeader);
                end
            end
            else begin
                reqHeaderOutQ.enq(reqHeader);
            end
        end
        else begin // Illegal RDMA request headers
            workCompGenReqOutQ.enq(errWorkCompGenReq);
            isNormalStateReg <= False;
        end
    endrule

    rule errFlushWR if (cntrl.isERR || (cntrl.isRTS && !isNormalStateReg));
        let {
            curPendingWR, totalReqPktNum, pmtuResidue, isNewWorkReq, isReliableConnection
        } = workReqPayloadGenQ.first;
        workReqPayloadGenQ.deq;

        // Only for RC and XRC output new WR as pending WR to generate WC
        if (isNewWorkReq && isReliableConnection) begin
            pendingWorkReqOutQ.enq(curPendingWR);
        end
    endrule

    rule errFlushPipelineQ if (cntrl.isERR || (cntrl.isRTS && !isNormalStateReg));
        flushInternalNormalStatePipelineQ;
    endrule

    interface pendingWorkReqPipeOut    = convertFifo2PipeOut(pendingWorkReqOutQ);
    interface rdmaReqDataStreamPipeOut = rdmaReqPipeOut;
    interface workCompGenReqPipeOut    = convertFifo2PipeOut(workCompGenReqOutQ);
endmodule
