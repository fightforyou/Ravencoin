#!/usr/bin/env python3
# Copyright (c) 2014-2016 The Bitcoin Core developers
# Copyright (c) 2017 The Raven Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test the rawtransaction RPCs for asset transactions.
"""
from io import BytesIO

from test_framework.test_framework import RavenTestFramework
from test_framework.util import *
from test_framework.mininode import CTransaction, CScriptTransfer

class RawAssetTransactionsTest(RavenTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 3

    def activate_assets(self):
        self.log.info("Generating RVN for node[0] and activating assets...")
        n0, n1, n2 = self.nodes[0], self.nodes[1], self.nodes[2]

        n0.generate(1)
        self.sync_all()
        n0.generate(431)
        self.sync_all()
        assert_equal("active", n0.getblockchaininfo()['bip9_softforks']['assets']['status'])

    def issue_reissue_transfer_test(self):
        self.log.info("Doing a big issue-reissue-transfer test...")
        n0, n1, n2 = self.nodes[0], self.nodes[1], self.nodes[2]

        ########################################
        # issue
        to_address = n0.getnewaddress()
        change_address = n0.getnewaddress()
        unspent = n0.listunspent()[0]
        inputs = [{k: unspent[k] for k in ['txid', 'vout']}]
        outputs = {
            'n1issueAssetXXXXXXXXXXXXXXXXWdnemQ': 500,
            change_address: float(unspent['amount']) - 500.0001,
            to_address: {
                'issue': {
                    'asset_name':       'TEST_ASSET',
                    'asset_quantity':   1000,
                    'units':            0,
                    'reissuable':       1,
                    'has_ipfs':         0,
                }
            }
        }
        tx_issue = n0.createrawtransaction(inputs, outputs)
        tx_issue_signed = n0.signrawtransaction(tx_issue)
        tx_issue_hash = n0.sendrawtransaction(tx_issue_signed['hex'])
        assert_is_hash_string(tx_issue_hash)
        self.log.info("issue tx: " + tx_issue_hash)

        n0.generate(1)
        self.sync_all()
        assert_equal(1000, n0.listmyassets('TEST_ASSET')['TEST_ASSET'])
        assert_equal(1, n0.listmyassets('TEST_ASSET!')['TEST_ASSET!'])

        ########################################
        # reissue
        unspent = n0.listunspent()[0]
        unspent_asset_owner = n0.listmyassets('TEST_ASSET!', True)['TEST_ASSET!']['outpoints'][0]

        inputs = [
            {k: unspent[k] for k in ['txid', 'vout']},
            {k: unspent_asset_owner[k] for k in ['txid', 'vout']},
        ]

        outputs = {
            'n1ReissueAssetXXXXXXXXXXXXXXWG9NLd': 100,
            change_address: float(unspent['amount']) - 100.0001,
            to_address: {
                'reissue': {
                    'asset_name':       'TEST_ASSET',
                    'asset_quantity':   1000,
                }
            }
        }

        tx_reissue = n0.createrawtransaction(inputs, outputs)
        tx_reissue_signed = n0.signrawtransaction(tx_reissue)
        tx_reissue_hash = n0.sendrawtransaction(tx_reissue_signed['hex'])
        assert_is_hash_string(tx_reissue_hash)
        self.log.info("reissue tx: " + tx_reissue_hash)

        n0.generate(1)
        self.sync_all()
        assert_equal(2000, n0.listmyassets('TEST_ASSET')['TEST_ASSET'])
        assert_equal(1, n0.listmyassets('TEST_ASSET!')['TEST_ASSET!'])

        self.sync_all()

        ########################################
        # transfer
        remote_to_address = n1.getnewaddress()
        unspent = n0.listunspent()[0]
        unspent_asset = n0.listmyassets('TEST_ASSET', True)['TEST_ASSET']['outpoints'][0]
        inputs = [
            {k: unspent[k] for k in ['txid', 'vout']},
            {k: unspent_asset[k] for k in ['txid', 'vout']},
        ]
        outputs = {
            change_address: float(unspent['amount']) - 0.0001,
            remote_to_address: {
                'transfer': {
                    'TEST_ASSET': 400
                }
            },
            to_address: {
                'transfer': {
                    'TEST_ASSET': float(unspent_asset['amount']) - 400
                }
            }
        }
        tx_transfer = n0.createrawtransaction(inputs, outputs)
        tx_transfer_signed = n0.signrawtransaction(tx_transfer)
        tx_hex = tx_transfer_signed['hex']

        ########################################
        # try tampering with the sig
        tx = CTransaction()
        f = BytesIO(hex_str_to_bytes(tx_hex))
        tx.deserialize(f)
        script_sig = bytes_to_hex_str(tx.vin[1].scriptSig)
        tampered_sig = script_sig[:-8] + "deadbeef"
        tx.vin[1].scriptSig = hex_str_to_bytes(tampered_sig)
        tampered_hex = bytes_to_hex_str(tx.serialize())
        assert_raises_rpc_error(-26, "mandatory-script-verify-flag-failed (Script failed an OP_EQUALVERIFY operation)",
                                n0.sendrawtransaction, tampered_hex)

        ########################################
        # try tampering with the asset script
        tx = CTransaction()
        f = BytesIO(hex_str_to_bytes(tx_hex))
        tx.deserialize(f)
        rvnt = '72766e74' #rvnt
        op_drop = '75'
        # change asset outputs from 400,600 to 500,500
        for i in range(1, 3):
            script_hex = bytes_to_hex_str(tx.vout[i].scriptPubKey)
            f = BytesIO(hex_str_to_bytes(script_hex[script_hex.index(rvnt) + len(rvnt):-len(op_drop)]))
            transfer = CScriptTransfer()
            transfer.deserialize(f)
            transfer.amount = 50000000000
            tampered_transfer = bytes_to_hex_str(transfer.serialize())
            tampered_script = script_hex[:script_hex.index(rvnt)] + rvnt + tampered_transfer + op_drop
            tx.vout[i].scriptPubKey = hex_str_to_bytes(tampered_script)
            t2 = CScriptTransfer()
            t2.deserialize(BytesIO(hex_str_to_bytes(tampered_transfer)))
        tampered_hex = bytes_to_hex_str(tx.serialize())
        assert_raises_rpc_error(-26, "mandatory-script-verify-flag-failed (Signature must be zero for failed CHECK(MULTI)SIG operation)",
                                n0.sendrawtransaction, tampered_hex)

        ########################################
        # try tampering with asset outs so ins and outs don't add up
        for n in (-20, -2, -1, 1, 2, 20):
            bad_outputs = {
                change_address: float(unspent['amount']) - 0.0001,
                remote_to_address: {
                    'transfer': {
                        'TEST_ASSET': 400
                    }
                },
                to_address: {
                    'transfer': {
                        'TEST_ASSET': float(unspent_asset['amount']) - (400 + n)
                    }
                }
            }
            tx_bad_transfer = n0.createrawtransaction(inputs, bad_outputs)
            tx_bad_transfer_signed = n0.signrawtransaction(tx_bad_transfer)
            tx_bad_hex = tx_bad_transfer_signed['hex']
            assert_raises_rpc_error(-26, "bad-tx-inputs-outputs-mismatch Bad Transaction - Assets would be burnt TEST_ASSET",
                                    n0.sendrawtransaction, tx_bad_hex)

        ########################################
        # try tampering with asset outs so they don't use proper units
        for n in (-0.1, -0.00000001, 0.1, 0.00000001):
            bad_outputs = {
                change_address: float(unspent['amount']) - 0.0001,
                remote_to_address: {
                    'transfer': {
                        'TEST_ASSET': (400 + n)
                    }
                },
                to_address: {
                    'transfer': {
                        'TEST_ASSET': float(unspent_asset['amount']) - (400 + n)
                    }
                }
            }
            tx_bad_transfer = n0.createrawtransaction(inputs, bad_outputs)
            tx_bad_transfer_signed = n0.signrawtransaction(tx_bad_transfer)
            tx_bad_hex = tx_bad_transfer_signed['hex']
            assert_raises_rpc_error(-26, "bad-txns-transfer-asset-amount-not-match-units",
                                    n0.sendrawtransaction, tx_bad_hex)

        ########################################
        # send the good transfer
        tx_transfer_hash = n0.sendrawtransaction(tx_hex)
        assert_is_hash_string(tx_transfer_hash)
        self.log.info("transfer tx: " + tx_transfer_hash)

        n0.generate(1)
        self.sync_all()
        assert_equal(1600, n0.listmyassets('TEST_ASSET')['TEST_ASSET'])
        assert_equal(1, n0.listmyassets('TEST_ASSET!')['TEST_ASSET!'])
        assert_equal(400, n1.listmyassets('TEST_ASSET')['TEST_ASSET'])


    def run_test(self):
        self.activate_assets()
        self.issue_reissue_transfer_test()

    # TODO: test block invalidation
    # TODO: test raw transactions (both properly and improperly constructed)
    # TODO: try issuing multiple assets at the same time (via raw)
    # TODO: work on issue_unique rpc call to issue multiples


if __name__ == '__main__':
    RawAssetTransactionsTest().main()
