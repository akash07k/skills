import assert from 'node:assert/strict';
import { test } from 'node:test';
import { lookupCustomer } from '../src/customer.js';
import { uniqueIds } from '../src/batch.js';

test('looks up a normalized customer ID', () => {
  assert.deepEqual(lookupCustomer(' ALICE '), { name: 'Alice' });
  assert.equal(lookupCustomer('unknown'), null);
});

test('removes duplicate normalized IDs', () => {
  assert.deepEqual(uniqueIds([' ALICE ', 'alice', 'BOB']), ['alice', 'bob']);
});
