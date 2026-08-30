import argparse

from src.assistant import Assistant


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="compressor",
        description=(
            "Start a Compressor unit. The unit name must match an entry in "
            "units.json, which is the tier list deciding who owns the system."
        ),
    )
    parser.add_argument(
        "unit_name",
        nargs="?",
        help='This machine\'s name in units.json, e.g. "Personal Laptop". '
        "Omit only when config.yaml pins a role and a unit_name.",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--units", default="units.json", help="Path to the unit tier list")
    args = parser.parse_args()

    Assistant(
        config_path=args.config,
        unit_name=args.unit_name,
        units_path=args.units,
    ).run()


if __name__ == "__main__":
    main()
