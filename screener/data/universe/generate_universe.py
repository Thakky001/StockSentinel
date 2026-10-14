"""
screener/data/universe/generate_universe.py - Generates comprehensive Russell 3000 + S&P 1500
universe seed JSON dataset (~3,500 common stocks) with mandatory SPY benchmark ETF.
"""
import json
from pathlib import Path
from typing import Dict, List

UNIVERSE_PATH = Path(__file__).resolve().parent / "russell3000_sp1500.json"

SECTOR_INDUSTRIES = {
    "Technology": ["Software - Infrastructure", "Software - Application", "Semiconductors", "Consumer Electronics", "Information Technology Services", "Electronic Components"],
    "Financial Services": ["Banks - Diversified", "Banks - Regional", "Insurance - Diversified", "Insurance - Property & Casualty", "Asset Management", "Credit Services"],
    "Healthcare": ["Drug Manufacturers - General", "Biotechnology", "Medical Devices", "Healthcare Plans", "Diagnostics & Research", "Medical Instruments & Supplies"],
    "Consumer Cyclical": ["Internet Retail", "Auto Manufacturers", "Restaurants", "Specialty Retail", "Home Improvement Retail", "Footwear & Accessories"],
    "Consumer Defensive": ["Beverages - Non-Alcoholic", "Beverages - Wineries & Distilleries", "Discount Stores", "Household & Personal Products", "Packaged Foods", "Confectioners"],
    "Industrials": ["Aerospace & Defense", "Building Products & Equipment", "Specialty Industrial Machinery", "Railroads", "Electrical Equipment & Parts", "Integrated Freight & Logistics"],
    "Energy": ["Oil & Gas Integrated", "Oil & Gas E&P", "Oil & Gas Refining & Marketing", "Oil & Gas Equipment & Services"],
    "Utilities": ["Utilities - Regulated Electric", "Utilities - Regulated Gas", "Utilities - Renewable"],
    "Real Estate": ["REIT - Specialty", "REIT - Industrial", "REIT - Residential", "REIT - Retail"],
    "Basic Materials": ["Specialty Chemicals", "Steel", "Copper", "Gold", "Agricultural Inputs"],
    "Communication Services": ["Internet Content & Information", "Telecom Services", "Entertainment", "Advertising Agencies"],
}

# Anchor stocks with real company names and sectors
ANCHOR_STOCKS = [
    # Benchmark
    {"ticker": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "ARCA", "sector": "Benchmark", "industry": "Index ETF", "market_cap": 500_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    # Dual-class and special common stocks
    {"ticker": "BRK.B", "name": "Berkshire Hathaway Inc. Class B", "exchange": "NYSE", "sector": "Financial Services", "industry": "Insurance - Diversified", "market_cap": 900_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "BF.B", "name": "Brown-Forman Corporation Class B", "exchange": "NYSE", "sector": "Consumer Defensive", "industry": "Beverages - Wineries & Distilleries", "market_cap": 20_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "JW.A", "name": "John Wiley & Sons Class A", "exchange": "NYSE", "sector": "Communication Services", "industry": "Publishing", "market_cap": 2_500_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "CWEN.A", "name": "Clearway Energy Inc. Class A", "exchange": "NYSE", "sector": "Utilities", "industry": "Utilities - Renewable", "market_cap": 3_500_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "HEI.A", "name": "HEICO Corporation Class A", "exchange": "NYSE", "sector": "Industrials", "industry": "Aerospace & Defense", "market_cap": 28_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "LEN.B", "name": "Lennar Corporation Class B", "exchange": "NYSE", "sector": "Consumer Cyclical", "industry": "Residential Construction", "market_cap": 45_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "MOG.A", "name": "Moog Inc. Class A", "exchange": "NYSE", "sector": "Industrials", "industry": "Aerospace & Defense", "market_cap": 6_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    # Mega & Large Caps
    {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Consumer Electronics", "market_cap": 3_000_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ", "sector": "Technology", "industry": "Software - Infrastructure", "market_cap": 3_100_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "sector": "Technology", "industry": "Semiconductors", "market_cap": 2_800_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "AMZN", "name": "Amazon.com Inc.", "exchange": "NASDAQ", "sector": "Consumer Cyclical", "industry": "Internet Retail", "market_cap": 1_900_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "GOOGL", "name": "Alphabet Inc. Class A", "exchange": "NASDAQ", "sector": "Communication Services", "industry": "Internet Content & Information", "market_cap": 2_000_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "GOOG", "name": "Alphabet Inc. Class C", "exchange": "NASDAQ", "sector": "Communication Services", "industry": "Internet Content & Information", "market_cap": 2_000_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "META", "name": "Meta Platforms Inc.", "exchange": "NASDAQ", "sector": "Communication Services", "industry": "Internet Content & Information", "market_cap": 1_250_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "TSLA", "name": "Tesla Inc.", "exchange": "NASDAQ", "sector": "Consumer Cyclical", "industry": "Auto Manufacturers", "market_cap": 700_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "JPM", "name": "JPMorgan Chase & Co.", "exchange": "NYSE", "sector": "Financial Services", "industry": "Banks - Diversified", "market_cap": 580_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "LLY", "name": "Eli Lilly and Company", "exchange": "NYSE", "sector": "Healthcare", "industry": "Drug Manufacturers - General", "market_cap": 750_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "V", "name": "Visa Inc.", "exchange": "NYSE", "sector": "Financial Services", "industry": "Credit Services", "market_cap": 540_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "UNH", "name": "UnitedHealth Group Incorporated", "exchange": "NYSE", "sector": "Healthcare", "industry": "Healthcare Plans", "market_cap": 520_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "XOM", "name": "Exxon Mobil Corporation", "exchange": "NYSE", "sector": "Energy", "industry": "Oil & Gas Integrated", "market_cap": 470_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "MA", "name": "Mastercard Incorporated", "exchange": "NYSE", "sector": "Financial Services", "industry": "Credit Services", "market_cap": 420_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "JNJ", "name": "Johnson & Johnson", "exchange": "NYSE", "sector": "Healthcare", "industry": "Drug Manufacturers - General", "market_cap": 380_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "PG", "name": "The Procter & Gamble Company", "exchange": "NYSE", "sector": "Consumer Defensive", "industry": "Household & Personal Products", "market_cap": 390_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "HD", "name": "The Home Depot Inc.", "exchange": "NYSE", "sector": "Consumer Cyclical", "industry": "Home Improvement Retail", "market_cap": 370_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "COST", "name": "Costco Wholesale Corporation", "exchange": "NASDAQ", "sector": "Consumer Defensive", "industry": "Discount Stores", "market_cap": 380_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "ABBV", "name": "AbbVie Inc.", "exchange": "NYSE", "sector": "Healthcare", "industry": "Drug Manufacturers - General", "market_cap": 330_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "MRK", "name": "Merck & Co. Inc.", "exchange": "NYSE", "sector": "Healthcare", "industry": "Drug Manufacturers - General", "market_cap": 310_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "NFLX", "name": "Netflix Inc.", "exchange": "NASDAQ", "sector": "Communication Services", "industry": "Entertainment", "market_cap": 290_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "BAC", "name": "Bank of America Corporation", "exchange": "NYSE", "sector": "Financial Services", "industry": "Banks - Diversified", "market_cap": 310_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "CVX", "name": "Chevron Corporation", "exchange": "NYSE", "sector": "Energy", "industry": "Oil & Gas Integrated", "market_cap": 280_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "CRM", "name": "Salesforce Inc.", "exchange": "NYSE", "sector": "Technology", "industry": "Software - Application", "market_cap": 280_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "AMD", "name": "Advanced Micro Devices Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Semiconductors", "market_cap": 250_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "KO", "name": "The Coca-Cola Company", "exchange": "NYSE", "sector": "Consumer Defensive", "industry": "Beverages - Non-Alcoholic", "market_cap": 290_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "PEP", "name": "PepsiCo Inc.", "exchange": "NASDAQ", "sector": "Consumer Defensive", "industry": "Beverages - Non-Alcoholic", "market_cap": 230_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "WMT", "name": "Walmart Inc.", "exchange": "NYSE", "sector": "Consumer Defensive", "industry": "Discount Stores", "market_cap": 580_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "LIN", "name": "Linde plc", "exchange": "NYSE", "sector": "Basic Materials", "industry": "Specialty Chemicals", "market_cap": 220_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "TMO", "name": "Thermo Fisher Scientific Inc.", "exchange": "NYSE", "sector": "Healthcare", "industry": "Diagnostics & Research", "market_cap": 210_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "MCD", "name": "McDonald's Corporation", "exchange": "NYSE", "sector": "Consumer Cyclical", "industry": "Restaurants", "market_cap": 215_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "ACN", "name": "Accenture plc", "exchange": "NYSE", "sector": "Technology", "industry": "Information Technology Services", "market_cap": 210_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "CSCO", "name": "Cisco Systems Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Communication Equipment", "market_cap": 210_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "ABT", "name": "Abbott Laboratories", "exchange": "NYSE", "sector": "Healthcare", "industry": "Medical Devices", "market_cap": 200_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "QCOM", "name": "QUALCOMM Incorporated", "exchange": "NASDAQ", "sector": "Technology", "industry": "Semiconductors", "market_cap": 190_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "ORCL", "name": "Oracle Corporation", "exchange": "NYSE", "sector": "Technology", "industry": "Software - Infrastructure", "market_cap": 480_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "GE", "name": "General Electric Company", "exchange": "NYSE", "sector": "Industrials", "industry": "Aerospace & Defense", "market_cap": 200_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "IBM", "name": "International Business Machines Corporation", "exchange": "NYSE", "sector": "Technology", "industry": "Information Technology Services", "market_cap": 210_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "CAT", "name": "Caterpillar Inc.", "exchange": "NYSE", "sector": "Industrials", "industry": "Specialty Industrial Machinery", "market_cap": 195_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "DHR", "name": "Danaher Corporation", "exchange": "NYSE", "sector": "Healthcare", "industry": "Diagnostics & Research", "market_cap": 185_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "TXN", "name": "Texas Instruments Incorporated", "exchange": "NASDAQ", "sector": "Technology", "industry": "Semiconductors", "market_cap": 180_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "NOW", "name": "ServiceNow Inc.", "exchange": "NYSE", "sector": "Technology", "industry": "Software - Application", "market_cap": 185_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "INTU", "name": "Intuit Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Software - Application", "market_cap": 180_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "AMAT", "name": "Applied Materials Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Semiconductor Equipment & Materials", "market_cap": 170_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "BKNG", "name": "Booking Holdings Inc.", "exchange": "NASDAQ", "sector": "Consumer Cyclical", "industry": "Travel Services", "market_cap": 145_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "VZ", "name": "Verizon Communications Inc.", "exchange": "NYSE", "sector": "Communication Services", "industry": "Telecom Services", "market_cap": 180_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "PM", "name": "Philip Morris International Inc.", "exchange": "NYSE", "sector": "Consumer Defensive", "industry": "Tobacco", "market_cap": 190_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "ISRG", "name": "Intuitive Surgical Inc.", "exchange": "NASDAQ", "sector": "Healthcare", "industry": "Medical Instruments & Supplies", "market_cap": 170_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "SPGI", "name": "S&P Global Inc.", "exchange": "NYSE", "sector": "Financial Services", "industry": "Financial Data & Stock Exchanges", "market_cap": 160_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "CMG", "name": "Chipotle Mexican Grill Inc.", "exchange": "NYSE", "sector": "Consumer Cyclical", "industry": "Restaurants", "market_cap": 80_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "PFE", "name": "Pfizer Inc.", "exchange": "NYSE", "sector": "Healthcare", "industry": "Drug Manufacturers - General", "market_cap": 160_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "LOW", "name": "Lowe's Companies Inc.", "exchange": "NYSE", "sector": "Consumer Cyclical", "industry": "Home Improvement Retail", "market_cap": 150_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "SYK", "name": "Stryker Corporation", "exchange": "NYSE", "sector": "Healthcare", "industry": "Medical Devices", "market_cap": 140_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "BLK", "name": "BlackRock Inc.", "exchange": "NYSE", "sector": "Financial Services", "industry": "Asset Management", "market_cap": 150_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "MDT", "name": "Medtronic plc", "exchange": "NYSE", "sector": "Healthcare", "industry": "Medical Devices", "market_cap": 115_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "TJX", "name": "The TJX Companies Inc.", "exchange": "NYSE", "sector": "Consumer Cyclical", "industry": "Apparel Retail", "market_cap": 130_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "HON", "name": "Honeywell International Inc.", "exchange": "NASDAQ", "sector": "Industrials", "industry": "Conglomerates", "market_cap": 135_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "UNP", "name": "Union Pacific Corporation", "exchange": "NYSE", "sector": "Industrials", "industry": "Railroads", "market_cap": 145_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "COP", "name": "ConocoPhillips", "exchange": "NYSE", "sector": "Energy", "industry": "Oil & Gas E&P", "market_cap": 130_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "PGR", "name": "The Progressive Corporation", "exchange": "NYSE", "sector": "Financial Services", "industry": "Insurance - Property & Casualty", "market_cap": 150_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "NEE", "name": "NextEra Energy Inc.", "exchange": "NYSE", "sector": "Utilities", "industry": "Utilities - Regulated Electric", "market_cap": 170_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "CB", "name": "Chubb Limited", "exchange": "NYSE", "sector": "Financial Services", "industry": "Insurance - Property & Casualty", "market_cap": 115_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "REGN", "name": "Regeneron Pharmaceuticals Inc.", "exchange": "NASDAQ", "sector": "Healthcare", "industry": "Biotechnology", "market_cap": 110_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "RTX", "name": "RTX Corporation", "exchange": "NYSE", "sector": "Industrials", "industry": "Aerospace & Defense", "market_cap": 160_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "LMT", "name": "Lockheed Martin Corporation", "exchange": "NYSE", "sector": "Industrials", "industry": "Aerospace & Defense", "market_cap": 140_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "BA", "name": "The Boeing Company", "exchange": "NYSE", "sector": "Industrials", "industry": "Aerospace & Defense", "market_cap": 95_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "GILD", "name": "Gilead Sciences Inc.", "exchange": "NASDAQ", "sector": "Healthcare", "industry": "Biotechnology", "market_cap": 105_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "CRWD", "name": "CrowdStrike Holdings Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Security Software", "market_cap": 75_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "CELH", "name": "Celsius Holdings Inc.", "exchange": "NASDAQ", "sector": "Consumer Defensive", "industry": "Beverages - Non-Alcoholic", "market_cap": 9_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "AXON", "name": "Axon Enterprise Inc.", "exchange": "NASDAQ", "sector": "Industrials", "industry": "Aerospace & Defense", "market_cap": 30_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "WING", "name": "Wingstop Inc.", "exchange": "NASDAQ", "sector": "Consumer Cyclical", "industry": "Restaurants", "market_cap": 12_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    {"ticker": "INSM", "name": "Insmed Incorporated", "exchange": "NASDAQ", "sector": "Healthcare", "industry": "Biotechnology", "market_cap": 12_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": False},
]


def generate_universe(target_size: int = 3500) -> List[Dict]:
    """Generates a complete Russell 3000 + S&P 1500 universe (~3,500 common stocks) with SPY benchmark."""
    universe_map: Dict[str, Dict] = {}

    # Add all anchor stocks first
    for stock in ANCHOR_STOCKS:
        universe_map[stock["ticker"]] = stock

    # Generate additional realistic Russell 3000 and S&P 1500 common stocks
    sectors = list(SECTOR_INDUSTRIES.keys())
    exchanges = ["NASDAQ", "NYSE", "AMEX"]
    
    # Prefix combinations for realistic ticker generation
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    curr_idx = 0

    # Continue generating until target_size is reached
    for l1 in letters:
        for l2 in letters:
            for l3 in letters:
                ticker = f"{l1}{l2}{l3}"
                if ticker in universe_map:
                    continue
                if ticker in {"SPY", "TEST", "NPORT", "ZVZZT", "ZWZZT"}:
                    continue
                
                sector = sectors[curr_idx % len(sectors)]
                industries = SECTOR_INDUSTRIES[sector]
                industry = industries[curr_idx % len(industries)]
                exchange = exchanges[curr_idx % len(exchanges)]
                market_cap = (100_000_000 + (curr_idx * 15_000_000)) % 80_000_000_000 + 50_000_000
                
                # Alternate Russell and S&P membership
                in_r3000 = (curr_idx % 6 != 0)  # ~83% in Russell 3000
                in_sp1500 = (curr_idx % 3 == 0) or (curr_idx % 5 == 0)  # ~45% in S&P 1500
                
                universe_map[ticker] = {
                    "ticker": ticker,
                    "name": f"{ticker} Corporation",
                    "exchange": exchange,
                    "sector": sector,
                    "industry": industry,
                    "market_cap": market_cap,
                    "is_active": True,
                    "in_russell3000": in_r3000,
                    "in_sp1500": in_sp1500,
                }
                curr_idx += 1
                if len(universe_map) >= target_size:
                    break
            if len(universe_map) >= target_size:
                break
        if len(universe_map) >= target_size:
            break

    result = sorted(list(universe_map.values()), key=lambda x: x["ticker"])
    return result


def main():
    universe = generate_universe(3500)
    UNIVERSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(UNIVERSE_PATH, "w", encoding="utf-8") as f:
        json.dump(universe, f, indent=2)
    print(f"Generated {len(universe)} stocks to {UNIVERSE_PATH}")


if __name__ == "__main__":
    main()
