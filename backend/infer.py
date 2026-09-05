import argparse
import json
from reconstruction import submission

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Восстановить только контрольные пропуски из private_features.csv"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="submission.csv")
    parser.add_argument("--model")
    args = parser.parse_args()
    print(
        json.dumps(submission(args.input, args.output, args.model), ensure_ascii=False)
    )
