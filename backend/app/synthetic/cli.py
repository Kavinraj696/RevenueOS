import sys
import click
from rich.console import Console
from rich.table import Table

from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.synthetic.generator import SyntheticDataGenerator
from app.synthetic.scenarios import SCENARIO_CONFIGS

console = Console()

@click.group()
def cli():
    """RevenueOS Synthetic Data Management CLI."""
    pass

@cli.command("generate-demo-data")
@click.option("--seed", default=42, type=int, help="Random seed for reproducible generation.")
@click.option("--scenario", multiple=True, help="Specific scenario ID(s) to generate. Defaults to all.")
def generate_demo_data(seed: int, scenario: tuple):
    """Generate deterministic synthetic demo data."""
    console.print(f"[bold cyan]Generating RevenueOS demo data with seed={seed}...[/bold cyan]")
    
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        generator = SyntheticDataGenerator(seed=seed)
        selected_scenarios = list(scenario) if scenario else None
        results = generator.generate_all(db, scenarios=selected_scenarios)
        
        table = Table(title="Generated Scenarios Summary")
        table.add_column("Scenario ID", style="cyan")
        table.add_column("Merchant Name", style="bold green")
        table.add_column("Payments", justify="right")
        table.add_column("Failures", justify="right", style="red")
        table.add_column("Recovered", justify="right", style="green")
        table.add_column("Subs", justify="right")
        table.add_column("Checkouts", justify="right")
        table.add_column("Leaks", justify="right")
        table.add_column("Opps", justify="right")

        for s_id, stats in results.items():
            table.add_row(
                s_id,
                stats["merchant_name"],
                str(stats["payments"]),
                str(stats["failed_payments"]),
                str(stats["recovered_payments"]),
                str(stats["subscriptions"]),
                str(stats["checkout_sessions"]),
                str(stats["leaks"]),
                str(stats["opportunities"]),
            )
        console.print(table)
        console.print("[bold green][SUCCESS] Demo data generation completed successfully.[/bold green]")
    finally:
        db.close()

@cli.command("reset-demo-data")
@click.option("--seed", default=42, type=int, help="Random seed for reproducible generation.")
def reset_demo_data(seed: int):
    """Reset database (wipe all tables and regenerate demo data)."""
    console.print("[bold yellow]Wiping and resetting all tables...[/bold yellow]")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    console.print("[green]Tables recreated successfully.[/green]")
    
    db = SessionLocal()
    try:
        generator = SyntheticDataGenerator(seed=seed)
        results = generator.generate_all(db)
        console.print(f"[bold green][SUCCESS] Reset complete! Seeded {len(results)} merchant scenarios.[/bold green]")
    finally:
        db.close()

if __name__ == "__main__":
    cli()
