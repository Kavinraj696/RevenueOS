import sys
import click
from rich.console import Console
from rich.table import Table

from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models import Merchant
from app.synthetic.generator import SyntheticDataGenerator
from app.synthetic.scenarios import SCENARIO_CONFIGS, get_scenario_config
from app.synthetic.validation import validate_dataset_integrity, calculate_observed_metrics

console = Console()


@click.group()
def cli():
    """RevenueOS Synthetic Commerce Data & Simulation CLI (Stage 2)."""
    pass


@cli.command("generate-demo-data")
@click.option("--seed", default=42, type=int, help="Random seed for reproducible generation.")
@click.option("--scenario", multiple=True, help="Specific scenario ID(s) or alias to generate. Options: healthy, payment_degradation, checkout_abandonment, subscription_failure, high_value_recovery, mixed, all.")
def generate_demo_data(seed: int, scenario: tuple):
    """Generate deterministic synthetic commerce demo data."""
    console.print(f"[bold cyan]Generating RevenueOS demo data with seed={seed}...[/bold cyan]")
    
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        generator = SyntheticDataGenerator(seed=seed)
        selected_scenarios = list(scenario) if scenario else None
        
        # If 'all' is passed in selected_scenarios, treat as None (generate all)
        if selected_scenarios and "all" in selected_scenarios:
            selected_scenarios = None

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


@cli.command("validate-data")
def validate_data():
    """Validate data integrity and display observed SQL metrics for all merchants."""
    console.print("[bold cyan]Running dataset integrity and metric validation...[/bold cyan]")
    db = SessionLocal()
    try:
        merchants = db.query(Merchant).all()
        if not merchants:
            console.print("[yellow]No merchants found in database. Run generate-demo-data first.[/yellow]")
            return

        for m in merchants:
            integ = validate_dataset_integrity(db, m.id)
            metrics = calculate_observed_metrics(db, m.id)
            
            status_text = "[bold green]PASS[/bold green]" if integ["valid"] else f"[bold red]FAIL ({integ['violations_count']} violations)[/bold red]"
            console.print(f"\n[bold underline]{m.name}[/bold underline] ({m.id}) — Integrity: {status_text}")
            if not integ["valid"]:
                for v in integ["violations"]:
                    console.print(f"  [red]• {v}[/red]")

            # Observed Metrics Table
            p_stats = metrics["payments"]
            c_stats = metrics["checkouts"]
            s_stats = metrics["subscriptions"]

            t = Table(title=f"Observed Metrics: {m.name}")
            t.add_column("Metric", style="cyan")
            t.add_column("Value", style="bold white")

            t.add_row("Total Payments", str(p_stats["total_count"]))
            t.add_row("Payment Failure Rate", f"{p_stats['overall_failure_rate'] * 100:.2f}%")
            t.add_row("Cluster Degradation Rate", f"{p_stats['cluster_failure_rate'] * 100:.2f}% (Control: {p_stats['control_failure_rate'] * 100:.2f}%)")
            t.add_row("Failed Payment Volume", f"INR {p_stats['failed_volume_inr']:,.2f}")
            t.add_row("Recoverable Volume", f"INR {p_stats['recoverable_volume_inr']:,.2f}")
            t.add_row("Non-Recoverable Volume", f"INR {p_stats['non_recoverable_volume_inr']:,.2f}")
            t.add_row("Checkout Abandonment Rate", f"{c_stats['abandonment_rate'] * 100:.2f}% (Lost: INR {c_stats['lost_cart_value_inr']:,.2f})")
            t.add_row("Subscription Churn/Fail Rate", f"{s_stats['renewal_failure_rate'] * 100:.2f}% (Affected MRR: INR {s_stats['affected_mrr_inr']:,.2f})")
            console.print(t)

        console.print("[bold green][SUCCESS] Validation completed.[/bold green]")
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
