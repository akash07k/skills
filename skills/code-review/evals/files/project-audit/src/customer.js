const customers = new Map([
  ['alice', { name: 'Alice' }],
]);

class CustomerIdNormalizer {
  normalize(raw) {
    return raw.trim().toLowerCase();
  }
}

export function lookupCustomer(raw) {
  const id = new CustomerIdNormalizer().normalize(raw);
  return customers.get(id) ?? null;
}
