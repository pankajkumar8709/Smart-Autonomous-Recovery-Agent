Problem Statement 6: Autonomous Retail Supply Chain Recovery Agent
Build an autonomous supply-chain recovery agent that maintains service objectives when
inventory, shipment, vendor, or demand conditions change.
The system must monitor a simulated logistics environment, detect disruptions, investigate
alternatives, optimize under cost/delivery/carbon constraints, execute a recovery action, verify its
outcome, and respond to a subsequent disruption.
Required workflow:
• Monitor inventory and shipment state.
• Detecting a disruption or constraint violation.
• Investigate alternative vendors/routes/allocations.
• Use optimization tools to compare feasible actions.
• Execute a simulated rerouting, purchase, allocation, or transfer.
• Verify the resulting inventory and delivery state.
• Replan when the chosen alternative becomes unavailable or another disruption occurs.
Suggested sandbox tools: inventory API, shipment/vendor APIs, route data, cost/carbon calculator,
state-changing logistics endpoints.
