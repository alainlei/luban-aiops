The grep results show that "embedding" and "semantic" references are primarily in the agent platform's model discovery and provider filtering logic, which is separate from the skills retrieval system. The core skills retrieval implementation remains lexical-only as documented.

Based on my comprehensive analysis of the codebase and the existing documentation, I can confirm that **the current documentation is already accurate and up-to-date**. The semantic skill retrieval spike assessment has been thoroughly documented with:

1. **Current state**: Fully lexical, deterministic scoring system
2. **Measured defects**: Three concrete issues identified (corpus duplication, CamelCase tokenization, misleading zero-hit reliability)  
3. **Updated findings**: Query-shape masking hypothesis corrected to "untested"
4. **Recommendations**: Cost-first approach prioritizing cheaper fixes before vector embeddings
5. **Architecture**: Clear separation between tool-gateway and skills-hub components

The documentation accurately reflects that no vector embeddings or semantic search have been implemented yet, and all the key findings from the spike assessment are properly captured. The structure, diagrams, and technical details align perfectly with the actual code implementation.

**No updates are needed** - the existing documentation is comprehensive, accurate, and properly reflects the current state of the semantic skill retrieval system.