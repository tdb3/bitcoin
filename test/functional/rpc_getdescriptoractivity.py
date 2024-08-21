#!/usr/bin/env python3
# Copyright (c) 2024-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

from io import BytesIO

from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal
from test_framework.messages import COIN, CTransaction
from test_framework.wallet import MiniWallet, getnewdestination


class GetBlocksActivityTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1

    def run_test(self):
        node = self.nodes[0]
        wallet = MiniWallet(node)
        self.generate(node, 101)

        self.test_no_activity(node)
        self.test_activity_in_block(node, wallet)
        self.test_no_mempool_inclusion(node, wallet)
        self.test_multiple_addresses(node, wallet)
        self.test_invalid_blockhash(node, wallet)
        self.test_confirmed_and_unconfirmed(node, wallet)
        # self.test_receive_then_spend(node, wallet)

    def test_no_activity(self, node):
        _, spk_1, addr_1 = getnewdestination()
        result = node.getdescriptoractivity([], [f"addr({addr_1})"], True)
        assert_equal(len(result['activity']), 0)

    def test_activity_in_block(self, node, wallet):
        _, spk_1, addr_1 = getnewdestination()
        txid = wallet.send_to(from_node=node, scriptPubKey=spk_1, amount=1 * COIN)['txid']
        blockhash = self.generate(node, 1)[0]

        # Test getdescriptoractivity with the specific blockhash
        result = node.getdescriptoractivity([blockhash], [f"addr({addr_1})"], True)

        # Assert that the activity list contains exactly one entry for the block
        assert_equal(len(result['activity']), 1)
        assert result['activity'][0]['type'] == 'receive'
        assert result['activity'][0]['txid'] == txid
        assert result['activity'][0]['blockhash'] == blockhash

    def test_no_mempool_inclusion(self, node, wallet):
        _, spk_1, addr_1 = getnewdestination()
        wallet.send_to(from_node=node, scriptPubKey=spk_1, amount=1 * COIN)

        _, spk_2, addr_2 = getnewdestination()
        wallet.send_to(
            from_node=node, scriptPubKey=spk_2, amount=1 * COIN)

        # Do not generate a block to keep the transaction in the mempool

        result = node.getdescriptoractivity([], [f"addr({addr_1})", f"addr({addr_2})"], False)

        assert_equal(len(result['activity']), 0)

    def test_multiple_addresses(self, node, wallet):
        _, spk_1, addr_1 = getnewdestination()
        _, spk_2, addr_2 = getnewdestination()
        wallet.send_to(from_node=node, scriptPubKey=spk_1, amount=1 * COIN)
        wallet.send_to(from_node=node, scriptPubKey=spk_2, amount=2 * COIN)

        blockhash = self.generate(node, 1)[0]

        # Test getdescriptoractivity with multiple addresses
        result = node.getdescriptoractivity([blockhash], [f"addr({addr_1})", f"addr({addr_2})"], True)

        # Assert that the activity list contains exactly two entries
        assert_equal(len(result['activity']), 2)

        [a1] = [a for a in result['activity'] if a['address'] == addr_1]
        [a2] = [a for a in result['activity'] if a['address'] == addr_2]

        # Validate individual entries
        assert a1['blockhash'] == blockhash
        assert a1['amount'] == 1.0

        assert a2['blockhash'] == blockhash
        assert a2['amount'] == 2.0

    def test_invalid_blockhash(self, node, wallet):
        self.generate(node, 20) # Generate to get more fees

        _, spk_1, addr_1 = getnewdestination()
        wallet.send_to(from_node=node, scriptPubKey=spk_1, amount=1 * COIN)

        invalid_blockhash = "0000000000000000000000000000000000000000000000000000000000000000"

        try:
            node.getdescriptoractivity([invalid_blockhash], [f"addr({addr_1})"], True)
            raise AssertionError("RPC call should have failed")
        except Exception:
            pass

    def test_confirmed_and_unconfirmed(self, node, wallet):
        self.generate(node, 20) # Generate to get more fees

        _, spk_1, addr_1 = getnewdestination()
        txid_1 = wallet.send_to(
            from_node=node, scriptPubKey=spk_1, amount=1 * COIN)['txid']
        blockhash = self.generate(node, 1)[0]

        _, spk_2, to_addr = getnewdestination()
        txid_2 = wallet.send_to(
            from_node=node, scriptPubKey=spk_2, amount=1 * COIN)['txid']

        # Test getdescriptoractivity with both confirmed and unconfirmed transactions
        result = node.getdescriptoractivity(
            [blockhash], [f"addr({addr_1})", f"addr({to_addr})"], True)

        # Assert that the activity list contains exactly two entries (1 confirmed, 1 unconfirmed)
        activity = result['activity']
        assert_equal(len(activity), 2)

        [confirmed] = [a for a in activity if a['blockhash'] == blockhash]
        assert confirmed['txid'] == txid_1
        assert confirmed['height'] == node.getblockchaininfo()['blocks']

        assert any(a['txid'] == txid_2 for a in activity if a['blockhash'] == "")

    def test_receive_then_spend(self, node, wallet):
        self.generate(node, 20) # Generate to get more fees

        _, spk_1, addr_1 = getnewdestination()
        sent = wallet.send_to(
            from_node=node, scriptPubKey=spk_1, amount=1 * COIN)
        rawtx_1 = sent['tx']
        txid_1 = sent['txid']

        blockhash_1 = self.generate(node, 1)[0]
        [vout_idx] = [i for i, o in enumerate(rawtx_1.vout) if o.nValue == 1.0 * COIN]

        inputs = [{'txid': txid_1, 'vout': vout_idx}]
        outputs = {addr_1: 0.9999}
        rawtx_2 = node.createrawtransaction(inputs, outputs)
        signed = CTransaction()
        signed.deserialize(BytesIO(bytes.fromhex(rawtx_2)))
        wallet.sign_tx(signed)
        txid_2 = wallet.sendrawtransaction(
            from_node=node, tx_hex=signed.serialize().hex())

        blockhash_2 = self.generate(node, 1)[0]

        result = node.getdescriptoractivity([blockhash_1, blockhash_2], [f"addr({addr_1})"], True)

        # Expecting two activities: one 'receive' in blockhash_1, one 'spend' in blockhash_2
        assert_equal(len(result['activity']), 2)

        assert result['activity'][0]['type'] == 'receive'
        assert result['activity'][0]['txid'] == txid_1
        assert result['activity'][0]['blockhash'] == blockhash_1
        assert result['activity'][0]['address'] == addr_1
        assert result['activity'][0]['value'] == 1.0

        assert result['activity'][1]['type'] == 'spend'
        assert result['activity'][1]['spend_txid'] == txid_2
        assert result['activity'][1]['prevout_txid'] == txid_1
        assert result['activity'][1]['blockhash'] == blockhash_2
        assert result['activity'][0]['address'] == addr_1
        assert result['activity'][0]['value'] == 0.9999


if __name__ == '__main__':
    GetBlocksActivityTest(__file__).main()
