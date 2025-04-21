# .github/scripts/wsl_smoke.py
import sys
import asyncio
import logging
from pathlib import Path

# Add project root to sys.path to allow importing mcp
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("wsl_smoke")

try:
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp import ClientSession, types
except ImportError as e:
    logger.error(f"Failed to import MCP library: {e}. Ensure MCP is installed in the environment.")
    sys.exit(2)

async def run_test(path_or_uri: str):
    """Connects to Jinni server, calls read_context, checks result."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jinni.server", "--log-level", "DEBUG"], # Run server as module with debug logging
        cwd=str(PROJECT_ROOT), # Run from project root
    )
    logger.info(f"Starting server: {server_params.command} {' '.join(server_params.args)}")

    try:
        async with stdio_client(server_params) as (read, write):
            logger.info("Connected to stdio server.")
            async with ClientSession(read, write) as session:
                init_response = await session.initialize()
                logger.info(f"MCP Session Initialized: {init_response}")

                tool_name = "read_context"
                # Use the provided path/uri as the project root
                # Pass empty lists for targets and rules to trigger default behavior
                # (processing the whole project root with default filters)
                arguments = {
                    "project_root": path_or_uri,
                    "targets": [],
                    "rules": []
                }
                logger.info(f"Calling tool '{tool_name}' with project_root='{path_or_uri}'")
                result = await session.call_tool(tool_name, arguments=arguments)
                logger.info(f"Tool '{tool_name}' returned: {type(result)}")

                if result.isError:
                    error_text = "Unknown error" # Default error
                    if result.content and isinstance(result.content[0], types.TextContent):
                        error_text = result.content[0].text
                    logger.error(f"Tool call failed! Error: {error_text}")
                    return False # Indicate failure
                else:
                    # Basic success check: If it didn't error, the path was likely resolved correctly.
                    # We could add checks for specific content if a file was created in WSL.
                    stdout_text = ""
                    if result.content and isinstance(result.content[0], types.TextContent):
                         stdout_text = result.content[0].text
                    logger.info(f"Tool call successful. Output length: {len(stdout_text)}")
                    # If we created e.g. /home/runner/testproj/hello.txt with "WSL OK"
                    # assert "File: hello.txt" in stdout_text
                    # assert "WSL OK" in stdout_text
                    return True # Indicate success

    except asyncio.TimeoutError:
        logger.error("Timeout connecting to or communicating with the MCP server.")
        return False
    except ConnectionRefusedError:
         logger.error("Connection refused. Is the server process starting correctly?")
         return False
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python wsl_smoke.py <path_or_uri_to_test>", file=sys.stderr)
        sys.exit(1)

    test_path = sys.argv[1]
    logger.info(f"Starting WSL smoke test with path/URI: {test_path}")

    success = asyncio.run(run_test(test_path))

    if success:
        logger.info("WSL Smoke Test PASSED!")
        sys.exit(0)
    else:
        logger.error("WSL Smoke Test FAILED!")
        sys.exit(1) 