
#!/usr/bin/env python3
import os, sys
required = ["STAGE","SES_FROM","PUBLIC_BASE"]
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print("Missing:", ", ".join(missing)); sys.exit(1)
print("All required env vars present.")
