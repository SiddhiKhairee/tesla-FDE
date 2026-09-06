import json

import pandas as pd

df = pd.read_csv("ai4i2020.csv")

summary = {
    "total_rows": int(len(df)),
    "machine_failure_1_count": int((df["Machine failure"] == 1).sum()),
    "machine_failure_0_count": int((df["Machine failure"] == 0).sum()),
    "failure_type_counts": {
        col: int((df[col] == 1).sum()) for col in ["TWF", "HDF", "PWF", "OSF", "RNF"]
    },
    "rows_with_no_failure_type_flagged_but_machine_failure_1": int(
        ((df["Machine failure"] == 1) & (df[["TWF", "HDF", "PWF", "OSF", "RNF"]].sum(axis=1) == 0)).sum()
    ),
    "rows_with_multiple_failure_types_flagged": int(
        (df[["TWF", "HDF", "PWF", "OSF", "RNF"]].sum(axis=1) > 1).sum()
    ),
    "product_id_unique_count": int(df["Product ID"].nunique()),
    "udi_unique_count": int(df["UDI"].nunique()),
}

print(json.dumps(summary, indent=2))

with open("data_summary.json", "w") as f:
    json.dump(summary, f, indent=2)
