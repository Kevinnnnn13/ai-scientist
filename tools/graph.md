---
config:
  flowchart:
    curve: linear
---
graph TD;
        **start**(<p>**start**</p>)
        llm(llm)
        tool(tool)
        **end**(<p>**end**</p>)
        **start** --> llm;
        llm --> **end**;
        classDef default fill:#f2f0ff,line-height:1.2
        classDef first fill-opacity:0
        classDef last fill:#bfb6fc