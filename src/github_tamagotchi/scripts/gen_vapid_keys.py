"""Generate VAPID key pair for web push notifications.

Usage: python -m github_tamagotchi.scripts.gen_vapid_keys
"""

import base64

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def main() -> None:
    key = generate_private_key(SECP256R1())
    private_der = key.private_bytes(Encoding.DER, PrivateFormat.TraditionalOpenSSL, NoEncryption())
    pub_bytes = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    private_b64 = base64.urlsafe_b64encode(private_der).rstrip(b"=").decode()
    public_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()

    print("Add these to your environment / k8s secret:")
    print(f"VAPID_PRIVATE_KEY={private_b64}")
    print(f"VAPID_PUBLIC_KEY={public_b64}")


if __name__ == "__main__":
    main()
