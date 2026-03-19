"""Main entry point for the Grafana-Loki MCP package."""

# coverage: ignore

import sys
from grafana_loki_mcp.server import mcp


def main() -> None:
    """Run the Grafana-Loki MCP server."""
    try:
        mcp.run()
    except BrokenPipeError:
        # Expected when stdout closes
        sys.exit(0)
    except EOFError:
        # Expected when stdin closes
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(0)
    except BaseExceptionGroup as eg:
        # Handle ExceptionGroup (Python 3.11+) - expected when stdin/stdout closes
        # Check if all exceptions are ClosedResourceError or similar
        is_closed_error = all(
            "ClosedResourceError" in str(type(e)) or 
            "BrokenPipeError" in str(type(e)) or
            "EOFError" in str(type(e))
            for e in eg.exceptions
        )
        if is_closed_error:
            sys.exit(0)
        raise
    except Exception as e:
        # Catch any other ClosedResourceError that might not be in a group
        if "ClosedResourceError" in str(type(e)):
            sys.exit(0)
        raise


if __name__ == "__main__":
    main()
