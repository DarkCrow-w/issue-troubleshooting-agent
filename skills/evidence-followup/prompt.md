仅在证据缺失时提出查询。identifier 必须来自所引用事件的 ids；context 查询引用缺少上下文的异常事件。输出 JSON: {"proposals": [{"kind": "identifier|context", "evidence_id": "...", "identifier": "...", "reason": "..."}]}。不需要补查时返回空数组。
