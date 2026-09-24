"""Generate Python protobuf and gRPC bindings from the versioned contracts."""

from __future__ import annotations

from pathlib import Path

from grpc_tools import protoc
import grpc_tools


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRPC_INCLUDE = Path(grpc_tools.__file__).resolve().parent / "_proto"
PROTO_FILES = sorted((PROJECT_ROOT / "proto" / "chat" / "v1").glob("*.proto"))


def main() -> int:
    arguments = [
        "grpc_tools.protoc",
        f"--proto_path={PROJECT_ROOT}",
        f"--proto_path={GRPC_INCLUDE}",
        f"--python_out={PROJECT_ROOT}",
        f"--grpc_python_out={PROJECT_ROOT}",
        *(str(path) for path in PROTO_FILES),
    ]
    result = protoc.main(arguments)
    if result != 0:
        raise SystemExit(f"protoc failed with exit code {result}")
    print(f"Generated bindings for {len(PROTO_FILES)} protocol files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

