class InMemoryBacktestRepository:
    def __init__(self):
        self.definitions = {}
        self.runs = {}
        self.input_runs = {}
        self.results = {}

    def find_run(self, input_hash): return self.input_runs.get(input_hash)
    def save_started(self, definition, run):
        self.definitions[definition.definition_id] = definition
        self.runs[run.run_id] = run
        self.input_runs[run.input_hash] = run
    def save_result(self, result):
        self.definitions[result.definition.definition_id] = result.definition
        self.runs[result.run.run_id] = result.run
        self.input_runs[result.run.input_hash] = result.run
        self.results[result.run.run_id] = result
    def save_failed(self, run):
        self.runs[run.run_id] = run
        self.input_runs[run.input_hash] = run
    def get_result(self, run_id): return self.results.get(run_id)

