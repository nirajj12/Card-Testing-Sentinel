export function randomHex(length: number): string {
  const byteCount = Math.ceil(length / 2);
  const bytes = new Uint8Array(byteCount);

  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
  } else {
    // These identifiers provide uniqueness and idempotency, not authentication.
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }

  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, length);
}
