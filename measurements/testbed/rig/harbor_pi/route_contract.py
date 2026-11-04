"""Identical task-prefix contract for all arms of the corrected pilot."""
CONTRACT_ID = 'declared-route-v1'
CONTRACT = '''Capability-route contract for this trial:
Use the assigned capability interface for every external operation. If MCP tools
or tool_search are available, use MCP tools (discover deferred tools with
tool_search). Otherwise use the explicitly provided CLI skills, reading the
relevant skill before using its CLI. Native shell/file tools remain available
for local calculations and artifact creation. Do not bypass an MCP capability
with CLI programs, curl, direct HTTP clients, or custom database clients; do not
invoke MCP servers from the CLI condition. Do not read credential files or print
secret values. If the assigned interface fails, report the failure rather than
switching interfaces. Self-contained tasks require no external operations.'''


def instruction_for(manifest, instruction):
    contract = manifest['harness'].get('harbor_route_contract')
    if contract is None:
        return instruction
    if contract not in (CONTRACT_ID, 'declared-route-v2'):
        raise ValueError('Unknown route contract')
    prefix=CONTRACT
    if contract=='declared-route-v2':
        prefix += ('\nArtifact completion contract: Keep artifact contents strictly to the requested '
                   'payload and format; put explanations in the final response instead. For repository '
                   'tasks, publish changes to the required remote branch and verify them there. '
                   'Uncommitted or unpushed working-tree files do not complete a repository change.')
    return prefix + '\n\n' + instruction
