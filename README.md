# PartTwin

PartTwin is an engineering assistant for finding possible replacements for discontinued parts.

## What is the problem?

When a part is discontinued, finding a replacement is not as simple as searching for a similar part. Things like voltage, connector, function, dimensions and missing specifications also need to be checked.

## What does PartTwin do?

PartTwin searches the available parts, finds similar candidates and checks them against important specifications. It also shows what matches, what does not match, and what still needs to be verified.

The engineer can then approve or reject the suggested replacement.

## Main Features

- Semantic search for finding similar parts
- Specification and candidate comparison
- Compatibility checks
- Detection of critical mismatches
- Risk and missing information checks
- Evidence and previous decision lookup
- Engineer approval before saving a replacement
- Knowledge Vault for storing approved decisions

## One Important Idea

**Similarity does not always mean compatibility.**

For example, a part may look very similar but still have the wrong voltage or connector. PartTwin uses separate compatibility rules to catch these cases instead of relying only on similarity.

## Workflow

```text
Understand
   ↓
Search
   ↓
Check
   ↓
Compare
   ↓
Investigate
   ↓
Risk & Evidence
   ↓
Recommendation
   ↓
Engineer Approval
   ↓
Knowledge Vault
