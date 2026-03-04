"""Phase 3 treasury and AI forecasting endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.services.treasury_service import (
    BoardPackRequest,
    BoardPackResponse,
    DailyVarianceReport,
    DailyVarianceRequest,
    ForecastInferenceRequest,
    ForecastInferenceResponse,
    HmrcObligation,
    HmrcScheduleRequest,
    LiquidityRequest,
    LiquidityResponse,
    PositionRequest,
    ConsolidatedPosition,
    SweepSimulationRequest,
    SweepSimulationResponse,
    TreasuryService,
    WeeklySummaryReport,
    WeeklySummaryRequest,
)

router = APIRouter(prefix="/treasury", tags=["Treasury"])
_svc = TreasuryService()


@router.post("/position", response_model=ConsolidatedPosition, summary="Consolidated cash position")
async def consolidated_position(payload: PositionRequest) -> ConsolidatedPosition:
    return _svc.consolidated_position(payload)


@router.post("/position/sweep-simulation", response_model=SweepSimulationResponse, summary="Intraday sweep simulation")
async def sweep_simulation(payload: SweepSimulationRequest) -> SweepSimulationResponse:
    return _svc.simulate_intraday_sweep(payload)


@router.post("/liquidity", response_model=LiquidityResponse, summary="Available liquidity and alert engine")
async def liquidity(payload: LiquidityRequest) -> LiquidityResponse:
    return _svc.available_liquidity_and_alerts(payload)


@router.post("/hmrc/obligations", response_model=list[HmrcObligation], summary="Populate HMRC obligations")
async def hmrc_obligations(payload: HmrcScheduleRequest) -> list[HmrcObligation]:
    return _svc.populate_hmrc_obligations(payload)


@router.post("/ai/forecast", response_model=ForecastInferenceResponse, summary="Run AI forecast validation pipeline")
async def ai_forecast(payload: ForecastInferenceRequest) -> ForecastInferenceResponse:
    return _svc.process_ai_forecast(payload)


@router.post("/reports/daily-variance", response_model=DailyVarianceReport, summary="Daily variance report")
async def daily_variance(payload: DailyVarianceRequest) -> DailyVarianceReport:
    return _svc.daily_variance_report(payload)


@router.post("/reports/weekly-summary", response_model=WeeklySummaryReport, summary="Weekly treasury summary")
async def weekly_summary(payload: WeeklySummaryRequest) -> WeeklySummaryReport:
    return _svc.weekly_summary_report(payload)


@router.post("/reports/monthly-board-pack", response_model=BoardPackResponse, summary="Monthly board pack export")
async def monthly_board_pack(payload: BoardPackRequest) -> BoardPackResponse:
    return _svc.monthly_board_pack(payload)
