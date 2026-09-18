// App.js
import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import BackgroundParticles from "./BackgroundParticles";

import { apiFetch, authenticate, AUTH_EXPIRED, restoreSession, setGuestGameToken, signOut } from "./api";

const TEAM_OPTIONS = [
  { value: "ARI", label: "Arizona Cardinals" },
  { value: "ATL", label: "Atlanta Falcons" },
  { value: "BAL", label: "Baltimore Ravens" },
  { value: "BUF", label: "Buffalo Bills" },
  { value: "CAR", label: "Carolina Panthers" },
  { value: "CHI", label: "Chicago Bears" },
  { value: "CIN", label: "Cincinnati Bengals" },
  { value: "CLE", label: "Cleveland Browns" },
  { value: "DAL", label: "Dallas Cowboys" },
  { value: "DEN", label: "Denver Broncos" },
  { value: "DET", label: "Detroit Lions" },
  { value: "GB", label: "Green Bay Packers" },
  { value: "HOU", label: "Houston Texans" },
  { value: "IND", label: "Indianapolis Colts" },
  { value: "JAX", label: "Jacksonville Jaguars" },
  { value: "KC", label: "Kansas City Chiefs" },
  { value: "LAC", label: "Los Angeles Chargers" },
  { value: "LAR", label: "Los Angeles Rams" },
  { value: "LV", label: "Las Vegas Raiders" },
  { value: "MIA", label: "Miami Dolphins" },
  { value: "MIN", label: "Minnesota Vikings" },
  { value: "NE", label: "New England Patriots" },
  { value: "NO", label: "New Orleans Saints" },
  { value: "NYG", label: "New York Giants" },
  { value: "NYJ", label: "New York Jets" },
  { value: "PHI", label: "Philadelphia Eagles" },
  { value: "PIT", label: "Pittsburgh Steelers" },
  { value: "SEA", label: "Seattle Seahawks" },
  { value: "SF", label: "San Francisco 49ers" },
  { value: "TB", label: "Tampa Bay Buccaneers" },
  { value: "TEN", label: "Tennessee Titans" },
  { value: "WAS", label: "Washington Commanders" },
];

const VALID_TEAM_CODES = new Set(TEAM_OPTIONS.map((team) => team.value));
const TEAM_NAME_BY_CODE = TEAM_OPTIONS.reduce((acc, team) => {
  acc[team.value] = team.label;
  return acc;
}, {});

const PLAY_TYPE_OPTIONS = [
  { value: "RUN", label: "RUN" },
  { value: "PASS", label: "PASS" },
];

function CustomSelect({
  value,
  onChange,
  options,
  placeholder,
  buttonStyle,
  menuStyle,
  optionStyle,
  isMobile,
}) {
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(null);
  const wrapperRef = useRef(null);

  const selectedOption = options.find((option) => option.value === value);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={wrapperRef} style={{ position: "relative", width: "100%" }}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        style={buttonStyle}
      >
        <span
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {selectedOption ? selectedOption.label : placeholder}
        </span>
        <span
          style={{
            marginLeft: "10px",
            fontSize: isMobile ? "11px" : "10px",
            color: "#2fc50e",
            flexShrink: 0,
          }}
        >
          ▼
        </span>
      </button>

      {open && (
        <div style={menuStyle}>
          {options.map((option) => {
            const isSelected = option.value === value;
            const isHovered = hovered === option.value;

            return (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
                onMouseEnter={() => setHovered(option.value)}
                onMouseLeave={() => setHovered(null)}
                style={{
                  ...optionStyle,
                  background: isSelected
                    ? "rgba(37, 235, 60, 0.18)"
                    : isHovered
                    ? "rgba(37, 235, 60, 0.10)"
                    : "transparent",
                  color: isSelected ? "#7CFF7C" : "#f8fafc",
                  borderLeft: isSelected
                    ? "3px solid #25eb2c"
                    : "3px solid transparent",
                }}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function App() {
  const [screen, setScreen] = useState("authChoice");
  const [authMode, setAuthMode] = useState("login");
  const [teamsSet, setTeamsSet] = useState(false);
  const [offense, setOffense] = useState("");
  const [defense, setDefense] = useState("");
  const [setupError, setSetupError] = useState("");
  const [predictionError, setPredictionError] = useState("");
  const [user, setUser] = useState(null);
  const [authReady, setAuthReady] = useState(false);
  const [isGuest, setIsGuest] = useState(() => sessionStorage.getItem("coordinaite_guest") === "true");
  const [showSavePrompt, setShowSavePrompt] = useState(false);
  const [authError, setAuthError] = useState("");
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [checkoutPending, setCheckoutPending] = useState(() => new URLSearchParams(window.location.search).get("success") === "true");
  const [subscription, setSubscription] = useState({
    tier: "free",
    subscription_status: null,
    tier2_access: false,
    tier2_models_available: false,
  });
  const [subscriptionMessage, setSubscriptionMessage] = useState("");
  const [activeGameId, setActiveGameId] = useState(null);

  const [authForm, setAuthForm] = useState({
    name: "",
    email: "",
    password: "",
  });

  const [form, setForm] = useState({
    down: 1,
    ydstogo: 10,
    yardline_100: 50,
    game_seconds_remaining: 900,
    qtr: 1,
    score_differential: 0,
  });

  const [prediction, setPrediction] = useState(null);
  const [pending, setPending] = useState({});
  const [playLog, setPlayLog] = useState([]);
  const [summary, setSummary] = useState({});

  const [actualPlayType, setActualPlayType] = useState("RUN");
  const [yardsGained, setYardsGained] = useState(0);

  const [historyGames, setHistoryGames] = useState([]);
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);

  const getTeamDisplay = useCallback((code) => {
    if (!code) return "";
    return TEAM_NAME_BY_CODE[code] ? `${TEAM_NAME_BY_CODE[code]} (${code})` : code;
  }, []);

  const fetchSubscriptionStatus = useCallback(async () => {
    try {
      const res = await apiFetch("/me/subscription");
      const data = await res.json();

      if (!res.ok) {
        return;
      }

      setSubscription({
        tier: data.tier || "free",
        subscription_status: data.subscription_status || null,
        tier2_access: Boolean(data.tier2_access),
        tier2_models_available: Boolean(data.tier2_models_available),
      });
      return data;
    } catch (error) {
      console.error("Error fetching subscription status:", error);
    }
  }, []);

  const refreshData = useCallback(async (gameId) => {
    if (!gameId) return;

    try {
      const encodedGameId = encodeURIComponent(gameId);
      const [pendingRes, playLogRes, summaryRes] = await Promise.all([
        apiFetch(`/pending?game_id=${encodedGameId}`),
        apiFetch(`/play-log?game_id=${encodedGameId}`),
        apiFetch(`/summary?game_id=${encodedGameId}`),
      ]);

      if (!pendingRes.ok || !playLogRes.ok || !summaryRes.ok) {
        throw new Error("Unable to refresh this game session.");
      }

      const pendingData = await pendingRes.json();
      const playLogData = await playLogRes.json();
      const summaryData = await summaryRes.json();

      setPending(pendingData);
      setPlayLog(playLogData);
      setSummary(summaryData);
    } catch (error) {
      console.error("Error refreshing data:", error);
    }
  }, []);

  const fetchUserGames = useCallback(async () => {
    try {
      const res = await apiFetch("/games");
      const data = await res.json();
      if (res.ok && Array.isArray(data)) {
        const sorted = [...data].sort((a, b) => {
          const aTime = new Date(a.updated_at || a.updatedAt || 0).getTime();
          const bTime = new Date(b.updated_at || b.updatedAt || 0).getTime();
          return bTime - aTime;
        });
        setHistoryGames(sorted);
      } else {
        setHistoryGames([]);
      }
    } catch (error) {
      console.error("Error fetching games:", error);
      setHistoryGames([]);
    }
  }, []);

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth <= 768);
    window.addEventListener("resize", handleResize);

    if (user) {
      setIsGuest(false);
      fetchUserGames();
      fetchSubscriptionStatus();
    }

    const params = new URLSearchParams(window.location.search);
    const success = params.get("success");
    const canceled = params.get("canceled");

    if (success === "true") {
      setSubscriptionMessage("Checkout completed. Checking your subscription...");
      if (user?.user_id) {
        fetchSubscriptionStatus();
      }
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (canceled === "true") {
      setSubscriptionMessage("Checkout was canceled.");
      window.history.replaceState({}, document.title, window.location.pathname);
    }

    return () => window.removeEventListener("resize", handleResize);
  }, [user, fetchSubscriptionStatus, fetchUserGames]);

  useEffect(() => {
    if (!user?.user_id || !checkoutPending) return;
    setScreen("upgrade");
    let stopped = false;
    let timer;
    let attempts = 0;
    const checkSubscription = async () => {
      const status = await fetchSubscriptionStatus();
      if (stopped) return;
      if (status?.tier2_access) {
        setSubscriptionMessage("Tier 2 activated. Your subscription is ready.");
        setCheckoutPending(false);
      } else if (++attempts < 15) {
        timer = setTimeout(checkSubscription, 2000);
      } else {
        setSubscriptionMessage("Your subscription is still being confirmed. Use Refresh subscription to check again.");
        setCheckoutPending(false);
      }
    };
    checkSubscription();
    return () => { stopped = true; clearTimeout(timer); };
  }, [user?.user_id, checkoutPending, fetchSubscriptionStatus]);

  const userGames = useMemo(() => historyGames, [historyGames]);

  const resetGameState = useCallback(() => {
    setForm({
      down: 1,
      ydstogo: 10,
      yardline_100: 50,
      game_seconds_remaining: 900,
      qtr: 1,
      score_differential: 0,
    });
    setPrediction(null);
    setPredictionError("");
    setPending({});
    setPlayLog([]);
    setSummary({});
    setActualPlayType("RUN");
    setYardsGained(0);
    setOffense("");
    setDefense("");
    setSetupError("");
    setTeamsSet(false);
    setActiveGameId(null);
    setGuestGameToken(null);
  }, []);

  useEffect(() => {
    let mounted = true;
    // Discard the old, unverified browser profile from phase one.
    localStorage.removeItem("coordinaite_current_user");
    localStorage.removeItem("coordinaite_guest");
    const onExpired = () => {
      setUser(null);
      setIsGuest(false);
      setHistoryGames([]);
      setShowSavePrompt(false);
      resetGameState();
      sessionStorage.removeItem("coordinaite_guest");
      setAuthError("Your session expired. Please sign in again.");
      setScreen("authChoice");
    };
    window.addEventListener(AUTH_EXPIRED, onExpired);
    restoreSession().then((data) => {
      if (!mounted) return;
      if (data) {
        setUser({ user_id: data.user_id, name: data.username, email: data.email });
        setIsGuest(false);
        sessionStorage.removeItem("coordinaite_guest");
        setScreen("teamSetup");
      } else if (sessionStorage.getItem("coordinaite_guest") === "true") {
        setScreen("teamSetup");
      }
    }).catch((error) => {
      if (mounted) setAuthError(error.message || "Could not connect to the server.");
    }).finally(() => {
      if (mounted) setAuthReady(true);
    });
    return () => {
      mounted = false;
      window.removeEventListener(AUTH_EXPIRED, onExpired);
    };
  }, [resetGameState]);

  const handleContinueAsGuest = async () => {
    try {
      await signOut();
      resetGameState();
      setIsGuest(true);
      setUser(null);
      setHistoryGames([]);
      setAuthError("");
      setSubscription({ tier: "free", subscription_status: null, tier2_access: false, tier2_models_available: false });
      sessionStorage.setItem("coordinaite_guest", "true");
      setScreen("teamSetup");
    } catch (error) {
      setAuthError("Could not start a guest session. Please try again.");
    }
  };

  const handleAuthSubmit = async (e) => {
    e.preventDefault();
    setAuthError("");
    const email = authForm.email.trim().toLowerCase();
    const password = authForm.password;
    const name = authForm.name.trim();
    if (!email || !password || (authMode === "signup" && !name)) {
      setAuthError("Please fill out all required fields.");
      return;
    }
    if (authMode === "signup" && password.length < 8) {
      setAuthError("Password must be at least 8 characters.");
      return;
    }
    try {
      const { user: signedIn, data } = await authenticate(authMode,
        authMode === "signup" ? { username: name, email, password } : { email, password });
      const continueGuestGame = isGuest && activeGameId;
      if (!continueGuestGame) resetGameState();
      setUser(signedIn);
      setIsGuest(false);
      sessionStorage.removeItem("coordinaite_guest");
      setSubscription({
        tier: data.tier || "free", subscription_status: data.subscription_status || null,
        tier2_access: false, tier2_models_available: false,
      });
      setAuthForm({ name: "", email: "", password: "" });
      setScreen(continueGuestGame ? "dashboard" : "teamSetup");
    } catch (error) {
      setAuthError(error.message || "Could not connect to the server.");
    }
  };

  const handleLogout = async () => {
    let errorMessage = "";
    try {
      await signOut();
    } catch (error) {
      errorMessage = "Could not finish signing out on the server. Reconnect and try again.";
    }
    sessionStorage.removeItem("coordinaite_guest");
    setUser(null);
    setIsGuest(false);
    setHistoryGames([]);
    setShowSavePrompt(false);
    setSubscription({ tier: "free", subscription_status: null, tier2_access: false, tier2_models_available: false });
    setSubscriptionMessage("");
    setCheckoutPending(false);
    setAuthError(errorMessage);
    resetGameState();
    setScreen("authChoice");
  };

  const handleSetTeams = async () => {
    setSetupError("");
    setPredictionError("");

    if (!offense || !defense) {
      setSetupError("Please select both teams before launching the dashboard.");
      return;
    }

    if (!VALID_TEAM_CODES.has(offense) || !VALID_TEAM_CODES.has(defense)) {
      setSetupError("Please select valid NFL teams from the dropdown menus.");
      return;
    }

    try {
      const res = await apiFetch(`/set-teams`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          offense,
          defense,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setSetupError(data.detail || "Unable to set teams.");
        return;
      }

      setActiveGameId(data.game_id);
      setGuestGameToken(data.guest_token);
      setTeamsSet(true);
      setScreen("dashboard");
    } catch (error) {
      console.error("Error setting teams:", error);
      setSetupError("Could not connect to the server.");
    }
  };

  const handleUpgradeCheckout = async () => {
    if (!user?.user_id) {
      setAuthError("You need to log in before purchasing Tier 2.");
      setScreen("authChoice");
      return;
    }

    try {
      setCheckoutLoading(true);
      setSubscriptionMessage("");

      const res = await apiFetch(`/create-checkout-session`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({}),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Failed to start checkout.");
      }

      if (data.url) {
        window.location.href = data.url;
        return;
      }

      throw new Error("No checkout URL returned.");
    } catch (error) {
      console.error("Checkout error:", error);
      setSubscriptionMessage(error.message || "Unable to start checkout.");
    } finally {
      setCheckoutLoading(false);
    }
  };

  const handlePredict = async () => {
    setPredictionError("");

    if (!teamsSet || !offense || !defense || !activeGameId) {
      setPredictionError("Set both teams before making predictions.");
      return;
    }

    const useTier2 =
      Boolean(user?.user_id) &&
      subscription.tier2_access &&
      subscription.tier2_models_available;

    const endpoint = useTier2 ? "/predict-tier2" : "/predict";

    try {
      const payload = { ...form, game_id: activeGameId };

      const res = await apiFetch(`${endpoint}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (!res.ok) {
        setPrediction(null);
        setPredictionError(data.detail || "Prediction failed.");
        return;
      }

      setPrediction(data);
      refreshData(activeGameId);
    } catch (error) {
      console.error("Error predicting play:", error);
      setPrediction(null);
      setPredictionError("Could not connect to the server.");
    }
  };

  const handleLogPlay = async () => {
    try {
      const res = await apiFetch(`/log-play`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          actual_play_type: actualPlayType,
          yards_gained: Number(yardsGained),
          game_id: activeGameId,
        }),
      });

      if (res.ok) {
        setPrediction(null);
        setYardsGained(0);
        refreshData(activeGameId);
      }
    } catch (error) {
      console.error("Error logging play:", error);
    }
  };

  const handleNewDrive = async () => {
    try {
      await apiFetch(`/new-drive`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ game_id: activeGameId }),
      });
      refreshData(activeGameId);
    } catch (error) {
      console.error("Error starting new drive:", error);
    }
  };

  const buildGameSnapshot = () => ({
    offense,
    defense,
    form,
    prediction,
    pending,
    play_log: playLog,
    summary,
    actualPlayType,
    yardsGained,
    teamsSet: true,
    game_id: activeGameId,
  });

  const handleSaveGame = async () => {
    if (!user) {
      setShowSavePrompt(true);
      return;
    }

    try {
      const res = await apiFetch(`/games`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          title: `${getTeamDisplay(offense) || "Offense"} vs ${getTeamDisplay(defense) || "Defense"}`,
          game_state: buildGameSnapshot(),
          game_id: activeGameId,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        console.error(data.detail || "Save failed");
        return;
      }

      await fetchUserGames();
      resetGameState();
      setScreen("teamSetup");
    } catch (error) {
      console.error("Error saving game:", error);
    }
  };

  const handleResumeGame = async (game) => {
    try {
      const res = await apiFetch(`/games/load`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ game_id: game.id }),
      });

      const data = await res.json();

      if (!res.ok) {
        console.error(data.detail || "Load failed");
        return;
      }

      const loaded = data.state || {};
      setGuestGameToken(null);
      setActiveGameId(data.game_id);
      setOffense(loaded.offense || "");
      setDefense(loaded.defense || "");
      setForm(
        loaded.form || {
          down: 1,
          ydstogo: 10,
          yardline_100: 50,
          game_seconds_remaining: 900,
          qtr: 1,
          score_differential: 0,
        }
      );
      setPrediction(loaded.prediction || null);
      setPredictionError("");
      setPending(loaded.pending || {});
      setPlayLog(loaded.play_log || []);
      setSummary(loaded.summary || {});
      setActualPlayType(loaded.actualPlayType || "RUN");
      setYardsGained(loaded.yardsGained ?? 0);
      setSetupError("");
      setTeamsSet(Boolean(loaded.offense && loaded.defense));
      setScreen("dashboard");
      refreshData(data.game_id);
    } catch (error) {
      console.error("Error resuming game:", error);
    }
  };

  const handleDeleteGame = async (gameId) => {
    if (!user) return;

    try {
      const res = await apiFetch(`/games/${gameId}`, {
        method: "DELETE",
      });

      if (res.ok) {
        fetchUserGames();
      }
    } catch (error) {
      console.error("Error deleting game:", error);
    }
  };

  const formatPct = (value) => {
    if (value == null) return "N/A";
    return `${(value * 100).toFixed(1)}%`;
  };

  const getConfidenceColor = (tier) => {
    if (tier === "HIGH" || tier === "STRONG") return "#22c55e";
    if (tier === "MODERATE") return "#f59e0b";
    return "#ef4444";
  };

  const styles = {
    page: {
      minHeight: "100vh",
      background: "transparent",
      color: "#f5f5f5",
      fontFamily: "Arial, sans-serif",
      padding: isMobile ? "16px" : "28px",
      position: "relative",
      zIndex: 1,
    },
    container: {
      maxWidth: "1400px",
      margin: "0 auto",
      position: "relative",
      zIndex: 1,
    },
    topBar: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: isMobile ? "flex-start" : "center",
      flexDirection: isMobile ? "column" : "row",
      gap: "14px",
      marginBottom: "18px",
    },
    topBarRight: {
      display: "flex",
      gap: "10px",
      flexWrap: "wrap",
      width: isMobile ? "100%" : "auto",
    },
    hero: {
      background:
        "linear-gradient(135deg, rgba(62, 136, 68, 0.86), rgba(32, 31, 31, 0.99))",
      border: "1px solid rgba(255, 255, 255, 0.18)",
      borderRadius: "20px",
      padding: isMobile ? "20px" : "28px",
      marginBottom: "24px",
      boxShadow: "0 20px 40px rgba(106, 102, 102, 0.56)",
    },
    heroTitle: {
      fontSize: isMobile ? "30px" : "44px",
      fontWeight: "800",
      margin: 0,
      color: "#0b0b0b",
      wordBreak: "break-word",
      lineHeight: isMobile ? "1.1" : "normal",
    },
    heroSubtitle: {
      marginTop: "10px",
      fontSize: isMobile ? "14px" : "16px",
      color: "#0f0f0f",
      wordBreak: "break-word",
      lineHeight: "1.4",
    },
    sectionTitle: {
      fontSize: isMobile ? "20px" : "22px",
      fontWeight: "800",
      color: "#f8fafc",
      marginBottom: "18px",
      marginTop: 0,
      wordBreak: "break-word",
    },
    card: {
      background: "rgba(0, 0, 0, 1)",
      border: "1px solid rgba(220, 226, 220, 0.16)",
      borderRadius: "18px",
      padding: isMobile ? "18px" : "22px",
      boxShadow: "0 12px 32px rgba(153, 227, 141, 0.22)",
      backdropFilter: "blur(6px)",
      minWidth: 0,
    },
    grid2: {
      display: "grid",
      gridTemplateColumns: isMobile ? "1fr" : "1.15fr 0.85fr",
      gap: "20px",
      marginBottom: "20px",
    },
    grid3: {
      display: "grid",
      gridTemplateColumns: isMobile ? "1fr" : "repeat(3, minmax(0, 1fr))",
      gap: "16px",
    },
    statGrid: {
      display: "grid",
      gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(4, minmax(0, 1fr))",
      gap: "14px",
      marginBottom: "20px",
    },
    statCard: {
      background: "linear-gradient(180deg, #000000, #000000)",
      border: "1px solid rgba(255, 255, 255, 0.16)",
      borderRadius: "16px",
      padding: isMobile ? "14px" : "16px",
      minWidth: 0,
    },
    statLabel: {
      fontSize: isMobile ? "11px" : "12px",
      color: "#dbd3d3",
      textTransform: "uppercase",
      letterSpacing: "0.08em",
      marginBottom: "8px",
      wordBreak: "break-word",
    },
    statValue: {
      fontSize: isMobile ? "22px" : "28px",
      fontWeight: "800",
      color: "#f8fafc",
      wordBreak: "break-word",
    },
    label: {
      display: "block",
      fontSize: "13px",
      fontWeight: "700",
      color: "#909192",
      marginBottom: "8px",
      wordBreak: "break-word",
    },
    input: {
      width: "100%",
      padding: "12px 14px",
      borderRadius: "12px",
      border: "1px solid rgba(29, 29, 29, 0.25)",
      background: "#121312",
      color: "#f8fafc",
      fontSize: isMobile ? "16px" : "15px",
      outline: "none",
      boxSizing: "border-box",
      minWidth: 0,
    },
    customSelectButton: {
      width: "100%",
      padding: isMobile ? "10px 12px" : "9px 12px",
      borderRadius: "12px",
      border: "1px solid rgba(29, 29, 29, 0.25)",
      background: "#121312",
      color: "#f8fafc",
      fontSize: isMobile ? "15px" : "14px",
      outline: "none",
      boxSizing: "border-box",
      minWidth: 0,
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      textAlign: "left",
      cursor: "pointer",
      minHeight: isMobile ? "42px" : "38px",
    },
    customSelectMenu: {
      position: "absolute",
      top: "calc(100% + 6px)",
      left: 0,
      right: 0,
      background: "#0d120d",
      border: "1px solid rgba(47, 197, 14, 0.25)",
      borderRadius: "12px",
      overflow: "hidden",
      boxShadow: "0 14px 30px rgba(0, 0, 0, 0.45)",
      zIndex: 50,
      maxHeight: "260px",
      overflowY: "auto",
    },
    customSelectOption: {
      width: "100%",
      padding: isMobile ? "10px 12px" : "9px 12px",
      background: "transparent",
      color: "#f8fafc",
      border: "none",
      textAlign: "left",
      cursor: "pointer",
      fontSize: isMobile ? "15px" : "14px",
      transition: "background 0.15s ease",
    },
    buttonPrimary: {
      padding: "12px 18px",
      borderRadius: "12px",
      border: "none",
      background: "linear-gradient(135deg, #25eb2c, #1dd81d)",
      color: "#000000",
      fontWeight: "700",
      cursor: "pointer",
      boxShadow: "0 10px 20px rgba(9, 59, 13, 0.25)",
      width: isMobile ? "100%" : "auto",
    },
    buttonSecondary: {
      padding: "12px 18px",
      borderRadius: "12px",
      border: "1px solid rgba(255, 255, 255, 0.47)",
      background: "#000000",
      color: "#2fc50e",
      fontWeight: "700",
      cursor: "pointer",
      width: isMobile ? "100%" : "auto",
    },
    buttonRow: {
      display: "flex",
      gap: "12px",
      marginTop: "18px",
      flexWrap: "wrap",
      flexDirection: isMobile ? "column" : "row",
    },
    badge: {
      display: "inline-block",
      padding: "6px 10px",
      borderRadius: "999px",
      fontSize: "12px",
      fontWeight: "800",
      letterSpacing: "0.05em",
      marginLeft: isMobile ? "0" : "10px",
      marginTop: isMobile ? "10px" : "0",
    },
    predictionBig: {
      fontSize: isMobile ? "30px" : "40px",
      fontWeight: "900",
      color: "#f8fafc",
      margin: "0 0 8px 0",
      wordBreak: "break-word",
      lineHeight: isMobile ? "1.1" : "normal",
    },
    predictionMeta: {
      color: "#94b899",
      fontSize: isMobile ? "13px" : "14px",
      marginBottom: "18px",
      wordBreak: "break-word",
    },
    metricRow: {
      display: "grid",
      gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
      gap: "12px",
      marginBottom: "18px",
    },
    metricBox: {
      background: "#0b200b",
      border: "1px solid rgba(26, 26, 27, 0.14)",
      borderRadius: "14px",
      padding: "14px",
      minWidth: 0,
    },
    metricLabel: {
      fontSize: "12px",
      color: "#ffffff",
      marginBottom: "8px",
      textTransform: "uppercase",
      letterSpacing: "0.08em",
      wordBreak: "break-word",
    },
    metricValue: {
      fontSize: isMobile ? "22px" : "26px",
      fontWeight: "800",
      color: "#f8fafc",
      wordBreak: "break-word",
    },
    strategyGrid: {
      display: "grid",
      gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
      gap: "12px",
      marginTop: "14px",
    },
    strategyItem: {
      background: "#34552d",
      borderRadius: "12px",
      padding: "12px",
      border: "1px solid rgba(255, 248, 248, 0.7)",
      minWidth: 0,
    },
    strategyLabel: {
      fontSize: "12px",
      color: "#000000",
      marginBottom: "6px",
      textTransform: "uppercase",
      letterSpacing: "0.08em",
      wordBreak: "break-word",
    },
    strategyValue: {
      fontWeight: "700",
      color: "#f8fafc",
      wordBreak: "break-word",
    },
    reasonBox: {
      marginTop: "12px",
      background: "rgba(37, 235, 60, 0.1)",
      border: "1px solid rgba(57, 58, 60, 0.22)",
      borderRadius: "12px",
      padding: "12px",
      color: "#dbeafe",
      wordBreak: "break-word",
      lineHeight: "1.4",
    },
    tableWrap: {
      overflowX: "auto",
      borderRadius: "16px",
      border: "1px solid rgba(7, 47, 8, 0.32)",
      WebkitOverflowScrolling: "touch",
    },
    table: {
      width: "100%",
      borderCollapse: "collapse",
      background: "#123004",
      minWidth: isMobile ? "700px" : "100%",
    },
    th: {
      textAlign: "left",
      padding: isMobile ? "10px" : "14px",
      color: "#c4c7ca",
      fontSize: isMobile ? "10px" : "12px",
      textTransform: "uppercase",
      letterSpacing: "0.08em",
      borderBottom: "1px solid rgba(45, 56, 45, 0.54)",
      background: "#032003",
      whiteSpace: "nowrap",
    },
    td: {
      padding: isMobile ? "10px" : "14px",
      borderBottom: "1px solid rgba(26, 76, 33, 0.26)",
      color: "#e5e7eb",
      fontSize: isMobile ? "12px" : "14px",
      whiteSpace: isMobile ? "nowrap" : "normal",
    },
    empty: {
      color: "#b8c5b8",
      fontSize: "15px",
      margin: 0,
    },
    setupWrap: {
      minHeight: "100vh",
      background: "transparent",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: isMobile ? "16px" : "24px",
      fontFamily: "Arial, sans-serif",
      position: "relative",
      zIndex: 1,
    },
    setupCard: {
      width: "100%",
      maxWidth: "720px",
      background: "rgba(49, 61, 49, 0.92)",
      border: "1px solid rgba(89, 90, 93, 0.16)",
      borderRadius: "22px",
      padding: isMobile ? "20px" : "30px",
      boxShadow: "0 20px 50px rgba(233, 234, 232, 0.3)",
      minWidth: 0,
    },
    setupTitle: {
      fontSize: isMobile ? "32px" : "42px",
      fontWeight: "900",
      color: "#f8fafc",
      margin: 0,
      wordBreak: "break-word",
      lineHeight: isMobile ? "1.1" : "normal",
    },
    setupSubtitle: {
      marginTop: "10px",
      color: "#000000",
      marginBottom: "24px",
      fontSize: isMobile ? "14px" : "16px",
      wordBreak: "break-word",
      lineHeight: "1.4",
    },
    authMiniText: {
      color: "#d3d7d4",
      fontSize: "13px",
      marginTop: "12px",
      marginBottom: 0,
      lineHeight: "1.5",
    },
    authTabs: {
      display: "flex",
      gap: "10px",
      marginBottom: "20px",
      flexDirection: isMobile ? "column" : "row",
    },
    statusPill: {
      display: "inline-block",
      borderRadius: "999px",
      padding: "7px 12px",
      fontSize: "12px",
      fontWeight: "800",
      background: "rgba(37, 235, 60, 0.12)",
      color: "#dfffe2",
      border: "1px solid rgba(37, 235, 60, 0.35)",
    },
    modalOverlay: {
      position: "fixed",
      inset: 0,
      background: "rgba(0, 0, 0, 0.65)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "16px",
      zIndex: 1000,
    },
    modalCard: {
      width: "100%",
      maxWidth: "460px",
      background: "rgba(25, 33, 25, 0.98)",
      border: "1px solid rgba(255, 255, 255, 0.14)",
      borderRadius: "20px",
      padding: isMobile ? "20px" : "24px",
      boxShadow: "0 20px 50px rgba(0, 0, 0, 0.45)",
    },
    gameCard: {
      background: "rgba(0, 0, 0, 0.82)",
      border: "1px solid rgba(255, 255, 255, 0.12)",
      borderRadius: "18px",
      padding: isMobile ? "16px" : "18px",
      marginBottom: "14px",
    },
    gameMeta: {
      color: "#b8c5b8",
      fontSize: "13px",
      marginTop: "6px",
      lineHeight: "1.5",
    },
    proPageWrap: {
      minHeight: "100vh",
      background: "transparent",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: isMobile ? "16px" : "28px",
      fontFamily: "Arial, sans-serif",
      position: "relative",
      zIndex: 1,
    },
    proPageCard: {
      width: "100%",
      maxWidth: "920px",
      background: "rgba(10, 14, 10, 0.9)",
      border: "1px solid rgba(255, 255, 255, 0.14)",
      borderRadius: "24px",
      padding: isMobile ? "22px" : "34px",
      boxShadow: "0 20px 50px rgba(153, 227, 141, 0.2)",
    },
    proTopBar: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: isMobile ? "stretch" : "center",
      flexDirection: isMobile ? "column" : "row",
      gap: "12px",
      marginBottom: "24px",
    },
    tierShowcaseWrap: {
      display: "flex",
      justifyContent: "center",
      marginTop: "12px",
    },
    tierShowcaseCard: {
      width: "100%",
      maxWidth: "380px",
      minHeight: isMobile ? "460px" : "560px",
      borderRadius: "26px",
      padding: isMobile ? "24px 20px" : "32px 26px",
      background:
        "linear-gradient(180deg, rgba(57, 103, 54, 0.97), rgba(5, 9, 5, 0.98))",
      border: "1px solid rgba(255, 255, 255, 0.18)",
      boxShadow: "0 18px 45px rgba(37, 235, 60, 0.18)",
      display: "flex",
      flexDirection: "column",
      justifyContent: "space-between",
    },
    tierLabel: {
      fontSize: "12px",
      color: "#c9f5cb",
      textTransform: "uppercase",
      letterSpacing: "0.18em",
      fontWeight: "800",
      marginBottom: "12px",
    },
    tierTitle: {
      fontSize: isMobile ? "34px" : "42px",
      fontWeight: "900",
      color: "#f8fafc",
      margin: 0,
      lineHeight: "1.05",
    },
    tierSubtitle: {
      marginTop: "12px",
      color: "#d8e4d8",
      fontSize: isMobile ? "14px" : "15px",
      lineHeight: "1.55",
    },
    tierFeatureList: {
      display: "grid",
      gap: "14px",
      marginTop: "26px",
    },
    tierFeatureItem: {
      background: "rgba(0, 0, 0, 0.36)",
      border: "1px solid rgba(255, 255, 255, 0.12)",
      borderRadius: "16px",
      padding: "14px 14px",
    },
    tierFeatureTitle: {
      color: "#7CFF7C",
      fontWeight: "800",
      fontSize: "15px",
      marginBottom: "6px",
    },
    tierFeatureText: {
      color: "#dce7dc",
      fontSize: "13px",
      lineHeight: "1.5",
    },
    tierFooterText: {
      marginTop: "24px",
      color: "#cfd8cf",
      fontSize: "13px",
      lineHeight: "1.55",
    },
  };

  const launchDisabled = !offense || !defense;
  if (!authReady) {
    return <div style={{ minHeight: "100vh", background: "#080b11", color: "white", padding: 32 }}>Loading CoordinAIte…</div>;
  }

  const tier2Enabled = Boolean(user) && subscription.tier2_access && subscription.tier2_models_available;

  if (screen === "authChoice") {
    return (
      <>
        <BackgroundParticles />
        <div style={styles.setupWrap}>
          <div style={styles.setupCard}>
            <div style={styles.topBar}>
              <div>
                <h1 style={styles.setupTitle}>
                  Coordin<span style={{ color: "#41d00e" }}>AI</span>te
                </h1>
                <p style={styles.setupSubtitle}>
                  Your live AI play predictor!
                </p>
              </div>
              <div style={styles.topBarRight}>
                <button
                  onClick={() => setScreen("upgrade")}
                  style={styles.buttonSecondary}
                >
                  Upgrade
                </button>
              </div>
            </div>

            <div style={styles.authTabs}>
              <button
                onClick={() => {
                  setAuthMode("login");
                  setAuthError("");
                }}
                style={authMode === "login" ? styles.buttonPrimary : styles.buttonSecondary}
              >
                Login
              </button>
              <button
                onClick={() => {
                  setAuthMode("signup");
                  setAuthError("");
                }}
                style={authMode === "signup" ? styles.buttonPrimary : styles.buttonSecondary}
              >
                Sign Up
              </button>
            </div>

            <form onSubmit={handleAuthSubmit}>
              {authMode === "signup" && (
                <div style={{ marginBottom: "16px" }}>
                  <label style={styles.label}>Name</label>
                  <input
                    type="text"
                    value={authForm.name}
                    onChange={(e) =>
                      setAuthForm({ ...authForm, name: e.target.value })
                    }
                    placeholder="Your name"
                    style={styles.input}
                  />
                </div>
              )}

              <div style={{ marginBottom: "16px" }}>
                <label style={styles.label}>Email</label>
                <input
                  type="email"
                  value={authForm.email}
                  onChange={(e) =>
                    setAuthForm({ ...authForm, email: e.target.value })
                  }
                  placeholder="you@example.com"
                  style={styles.input}
                />
              </div>

              <div>
                <label style={styles.label}>Password</label>
                <input
                  type="password"
                  value={authForm.password}
                  onChange={(e) =>
                    setAuthForm({ ...authForm, password: e.target.value })
                  }
                  placeholder="Enter password"
                  style={styles.input}
                />
              </div>

              {authError && (
                <div style={{ ...styles.reasonBox, color: "#fca5a5" }}>{authError}</div>
              )}

              <div style={styles.buttonRow}>
                <button type="submit" style={styles.buttonPrimary}>
                  {authMode === "login" ? "Enter Account" : "Create Account"}
                </button>
                <button
                  type="button"
                  onClick={handleContinueAsGuest}
                  style={styles.buttonSecondary}
                >
                  Continue as Guest
                </button>
              </div>
            </form>

            <p style={styles.authMiniText}>
              Guests can still use the prediction dashboard, but saved games and
              account history are only available after login.
            </p>
          </div>
        </div>
      </>
    );
  }

  if (screen === "teamSetup" && !teamsSet) {
    return (
      <>
        <BackgroundParticles />
        <div style={styles.setupWrap}>
          <div style={styles.setupCard}>
            <div style={styles.topBar}>
              <div>
                <h1 style={styles.setupTitle}>
                  Coordin<span style={{ color: "#41d00e" }}>AI</span>te
                </h1>
                <p style={styles.setupSubtitle}>
                  Set the offense and defense to begin the live prediction dashboard.
                </p>
              </div>
              <div style={styles.topBarRight}>
                <span style={styles.statusPill}>
                  {user
                    ? `Logged in as ${user.name}${tier2Enabled ? " • Tier 2" : ""}`
                    : "Guest Mode"}
                </span>
                <button
                  onClick={() => setScreen("upgrade")}
                  style={styles.buttonSecondary}
                >
                  Upgrade
                </button>
                {user ? (
                  <>
                    <button
                      onClick={() => setScreen("history")}
                      style={styles.buttonSecondary}
                    >
                      History
                    </button>
                    <button onClick={handleLogout} style={styles.buttonSecondary}>
                      Logout
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => setScreen("authChoice")}
                    style={styles.buttonSecondary}
                  >
                    Login / Sign Up
                  </button>
                )}
              </div>
            </div>

            <div style={styles.grid2}>
              <div>
                <label style={styles.label}>Offense Team</label>
                <CustomSelect
                  value={offense}
                  onChange={(selectedValue) => {
                    setOffense(selectedValue);
                    setSetupError("");
                  }}
                  options={TEAM_OPTIONS}
                  placeholder="Select offense team"
                  buttonStyle={styles.customSelectButton}
                  menuStyle={styles.customSelectMenu}
                  optionStyle={styles.customSelectOption}
                  isMobile={isMobile}
                />
              </div>

              <div>
                <label style={styles.label}>Defense Team</label>
                <CustomSelect
                  value={defense}
                  onChange={(selectedValue) => {
                    setDefense(selectedValue);
                    setSetupError("");
                  }}
                  options={TEAM_OPTIONS}
                  placeholder="Select defense team"
                  buttonStyle={styles.customSelectButton}
                  menuStyle={styles.customSelectMenu}
                  optionStyle={styles.customSelectOption}
                  isMobile={isMobile}
                />
              </div>
            </div>

            {setupError && (
              <div style={{ ...styles.reasonBox, color: "#fca5a5" }}>{setupError}</div>
            )}

            <div style={styles.buttonRow}>
              <button
                onClick={handleSetTeams}
                style={{
                  ...styles.buttonPrimary,
                  opacity: launchDisabled ? 0.65 : 1,
                  cursor: launchDisabled ? "not-allowed" : "pointer",
                }}
                disabled={launchDisabled}
              >
                Launch Dashboard
              </button>
              {user && (
                <button
                  onClick={() => setScreen("history")}
                  style={styles.buttonSecondary}
                >
                  View Saved Games
                </button>
              )}
            </div>
          </div>
        </div>
      </>
    );
  }

  if (screen === "upgrade") {
    return (
      <>
        <BackgroundParticles />
        <div style={styles.proPageWrap}>
          <div style={styles.proPageCard}>
            <div style={styles.proTopBar}>
              <div>
                <h1 style={styles.setupTitle}>
                  Coordin<span style={{ color: "#41d00e" }}>AI</span>te<span style={{ color: "#41d00e", marginLeft: "20px" }}>Pro</span>
                </h1>
                <p style={{ ...styles.setupSubtitle, marginBottom: 0, color: "#aaaaaa" }}>
                  Unlock the next layer of game intelligence with Tier 2.
                </p>
              </div>
              <div style={styles.topBarRight}>
                <button
                  onClick={() => setScreen(user || isGuest ? (teamsSet ? "dashboard" : "teamSetup") : "authChoice")}
                  style={styles.buttonSecondary}
                >
                  Back
                </button>
              </div>
            </div>

            <div style={styles.tierShowcaseWrap}>
              <div style={styles.tierShowcaseCard}>
                <div>
                  <div style={styles.tierLabel}>Premium Plan</div>
                  <h2 style={styles.tierTitle}>Tier 2</h2>
                  <div style={{ color: "#000000", fontSize: "20px", fontWeight: "bold", marginBottom: "10px" }}>
                    $10 / month
                  </div>
                  <div style={styles.tierSubtitle}>
                    Built for users who want more than just run and pass prediction.
                  </div>

                  <div style={styles.tierFeatureList}>
                    <div style={styles.tierFeatureItem}>
                      <div style={styles.tierFeatureTitle}>Play Direction Prediction</div>
                      <div style={styles.tierFeatureText}>
                        See whether the offense is leaning left, middle, or right
                        before the snap.
                      </div>
                    </div>

                    <div style={styles.tierFeatureItem}>
                      <div style={styles.tierFeatureTitle}>Play Concept Prediction</div>
                      <div style={styles.tierFeatureText}>
                        Unlock concept-level insight such as screens, quick game,
                        deep shots, inside runs, and edge-based runs.
                      </div>
                    </div>

                    <div style={styles.tierFeatureItem}>
                      <div style={styles.tierFeatureTitle}>Expanded Defensive Insight</div>
                      <div style={styles.tierFeatureText}>
                        Make more informed calls by pairing base play-type prediction
                        with direction and concept tendencies.
                      </div>
                    </div>
                  </div>

                  {user ? (
                    <div style={{ marginTop: "18px" }}>
                      <div style={styles.reasonBox}>
                        Current tier:{" "}
                        <strong>{tier2Enabled ? "Tier 2 Active" : subscription.tier || "free"}</strong>
                        {subscription.subscription_status ? (
                          <>
                            <br />
                            Subscription status:{" "}
                            <strong>{subscription.subscription_status}</strong>
                          </>
                        ) : null}
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: "18px" }}>
                      <div style={styles.reasonBox}>
                        Log in to purchase Tier 2 and unlock premium predictions.
                      </div>
                    </div>
                  )}

                  {subscriptionMessage && (
                    <div
                      style={{
                        ...styles.reasonBox,
                        color:
                          subscriptionMessage.toLowerCase().includes("successful") ||
                          subscriptionMessage.toLowerCase().includes("activated")
                            ? "#bbf7d0"
                            : "#fca5a5",
                      }}
                    >
                      {subscriptionMessage}
                    </div>
                  )}
                </div>

                <div>
                  <div style={styles.tierFooterText}>
                    CoordinAIte Pro Tier 2 is designed to give you a more detailed
                    pre-snap picture without changing the look and feel of your current workflow.
                  </div>

                  <div style={styles.buttonRow}>
                    {tier2Enabled ? (
                      <button
                        onClick={() => setScreen(teamsSet ? "dashboard" : "teamSetup")}
                        style={styles.buttonPrimary}
                      >
                        Tier 2 Active
                      </button>
                    ) : (
                      <button
                        onClick={handleUpgradeCheckout}
                        style={{
                          ...styles.buttonPrimary,
                          opacity: checkoutLoading ? 0.75 : 1,
                          cursor: checkoutLoading ? "wait" : "pointer",
                        }}
                        disabled={checkoutLoading}
                      >
                        {checkoutLoading ? "Opening Checkout..." : "Subscribe to Tier 2"}
                      </button>
                    )}

                    {user && (
                      <button
                        onClick={fetchSubscriptionStatus}
                        style={styles.buttonSecondary}
                      >
                        Refresh subscription
                      </button>
                    )}

                    {!user && (
                      <button
                        onClick={() => setScreen("authChoice")}
                        style={styles.buttonSecondary}
                      >
                        Login / Sign Up
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </>
    );
  }

  if (screen === "history") {
    return (
      <>
        <BackgroundParticles />
        <div style={styles.page}>
          <div style={styles.container}>
            <div style={styles.topBar}>
              <div>
                <h1
                  style={{
                    ...styles.heroTitle,
                    color: "#f8fafc",
                  }}
                >
                  Saved Game History
                </h1>
                <div
                  style={{
                    ...styles.heroSubtitle,
                    color: "#b8c5b8",
                  }}
                >
                  Resume prior game states or remove old saves from your account.
                </div>
              </div>
              <div style={styles.topBarRight}>
                <button
                  onClick={() => setScreen(teamsSet ? "dashboard" : "teamSetup")}
                  style={styles.buttonSecondary}
                >
                  Back
                </button>
                <button onClick={handleLogout} style={styles.buttonSecondary}>
                  Logout
                </button>
              </div>
            </div>

            <div style={styles.card}>
              {userGames.length === 0 ? (
                <p style={styles.empty}>No saved games yet.</p>
              ) : (
                userGames.map((game) => (
                  <div key={game.id} style={styles.gameCard}>
                    <h3 style={{ margin: 0, color: "#f8fafc" }}>{game.title}</h3>
                    <div style={styles.gameMeta}>
                      Saved:{" "}
                      {new Date(
                        game.updated_at || game.updatedAt || game.created_at || Date.now()
                      ).toLocaleString()}
                      <br />
                      Quarter: {game.game_state?.form?.qtr ?? "N/A"} | Down:{" "}
                      {game.game_state?.form?.down ?? "N/A"} | Distance:{" "}
                      {game.game_state?.form?.ydstogo ?? "N/A"}
                      <br />
                      Logged Plays: {game.game_state?.play_log?.length ?? 0}
                    </div>
                    <div style={styles.buttonRow}>
                      <button
                        onClick={() => handleResumeGame(game)}
                        style={styles.buttonPrimary}
                      >
                        Resume Game
                      </button>
                      <button
                        onClick={() => handleDeleteGame(game.id)}
                        style={styles.buttonSecondary}
                      >
                        Delete Save
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <BackgroundParticles />
      <div style={styles.page}>
        <div style={styles.container}>
          <div style={styles.topBar}>
            <div style={styles.topBarRight}>
              <span style={styles.statusPill}>
                {user
                  ? `Account: ${user.name}${tier2Enabled ? " • Tier 2" : ""}`
                  : "Guest Session"}
              </span>
            </div>
            <div style={styles.topBarRight}>
              <button
                onClick={() => {
                  resetGameState();
                  setScreen("teamSetup");
                }}
                style={styles.buttonSecondary}
              >
                Home
              </button>
              <button
                onClick={() => setScreen("upgrade")}
                style={styles.buttonSecondary}
              >
                Upgrade
              </button>
              {user && (
                <button onClick={() => setScreen("history")} style={styles.buttonSecondary}>
                  History
                </button>
              )}
              {user ? (
                <button onClick={handleLogout} style={styles.buttonSecondary}>
                  Logout
                </button>
              ) : (
                <button
                  onClick={() => setScreen("authChoice")}
                  style={styles.buttonSecondary}
                >
                  Login / Sign Up
                </button>
              )}
            </div>
          </div>

          <div style={styles.hero}>
            <h1 style={styles.heroTitle}>
              Football AI Defensive Assistant
              {tier2Enabled && (
                <span style={{ color: "#1fc022", marginLeft: "10px", fontWeight: "bold" }}>
                  Pro
                </span>
              )}
            </h1>
            <div style={styles.heroSubtitle}>
              Live play prediction, defensive recommendation, and in-game tracking
              {offense && defense && (
                <>
                  <br />
                  {getTeamDisplay(offense)} offense vs {getTeamDisplay(defense)} defense
                </>
              )}
              <br />
              Mode: {tier2Enabled ? "Tier 2 prediction enabled" : "Base prediction"}
            </div>
          </div>

          <div style={styles.statGrid}>
            <div style={styles.statCard}>
              <div style={styles.statLabel}>Total Predictions</div>
              <div style={styles.statValue}>{summary.total_predictions ?? 0}</div>
            </div>

            <div style={styles.statCard}>
              <div style={styles.statLabel}>Game Accuracy</div>
              <div style={styles.statValue}>{formatPct(summary.game_accuracy)}</div>
            </div>

            <div style={styles.statCard}>
              <div style={styles.statLabel}>Last 5 Accuracy</div>
              <div style={styles.statValue}>{formatPct(summary.last_5_accuracy)}</div>
            </div>

            <div style={styles.statCard}>
              <div style={styles.statLabel}>Last 10 Accuracy</div>
              <div style={styles.statValue}>{formatPct(summary.last_10_accuracy)}</div>
            </div>
          </div>

          <div style={styles.grid2}>
            <div style={styles.card}>
              <h2 style={styles.sectionTitle}>Game Situation</h2>

              <div style={styles.grid3}>
                <div>
                  <label style={styles.label}>Down</label>
                  <input
                    type="number"
                    value={form.down}
                    onChange={(e) =>
                      setForm({ ...form, down: Number(e.target.value) })
                    }
                    style={styles.input}
                  />
                </div>

                <div>
                  <label style={styles.label}>Yards to Go</label>
                  <input
                    type="number"
                    value={form.ydstogo}
                    onChange={(e) =>
                      setForm({ ...form, ydstogo: Number(e.target.value) })
                    }
                    style={styles.input}
                  />
                </div>

                <div>
                  <label style={styles.label}>Yardline (0-100)</label>
                  <input
                    type="number"
                    value={form.yardline_100}
                    onChange={(e) =>
                      setForm({ ...form, yardline_100: Number(e.target.value) })
                    }
                    style={styles.input}
                  />
                </div>

                <div>
                  <label style={styles.label}>Game Seconds Remaining</label>
                  <input
                    type="number"
                    value={form.game_seconds_remaining}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        game_seconds_remaining: Number(e.target.value),
                      })
                    }
                    style={styles.input}
                  />
                </div>

                <div>
                  <label style={styles.label}>Quarter</label>
                  <input
                    type="number"
                    value={form.qtr}
                    onChange={(e) =>
                      setForm({ ...form, qtr: Number(e.target.value) })
                    }
                    style={styles.input}
                  />
                </div>

                <div>
                  <label style={styles.label}>Score Differential</label>
                  <input
                    type="number"
                    value={form.score_differential}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        score_differential: Number(e.target.value),
                      })
                    }
                    style={styles.input}
                  />
                </div>
              </div>

              {predictionError && (
                <div style={{ ...styles.reasonBox, color: "#fca5a5" }}>{predictionError}</div>
              )}

              <div style={styles.buttonRow}>
                <button onClick={handlePredict} style={styles.buttonPrimary}>
                  Predict Next Play
                </button>
                <button onClick={handleNewDrive} style={styles.buttonSecondary}>
                  Start New Drive
                </button>
                <button onClick={handleSaveGame} style={styles.buttonSecondary}>
                  Save Game
                </button>
              </div>
            </div>

            <div style={styles.card}>
              <h2 style={styles.sectionTitle}>Log Actual Play</h2>

              <div style={styles.grid2}>
                <div>
                  <label style={styles.label}>Actual Play Type</label>
                  <CustomSelect
                    value={actualPlayType}
                    onChange={(selectedValue) => setActualPlayType(selectedValue)}
                    options={PLAY_TYPE_OPTIONS}
                    placeholder="Select play type"
                    buttonStyle={styles.customSelectButton}
                    menuStyle={styles.customSelectMenu}
                    optionStyle={styles.customSelectOption}
                    isMobile={isMobile}
                  />
                </div>

                <div>
                  <label style={styles.label}>Yards Gained</label>
                  <input
                    type="number"
                    placeholder="0"
                    value={yardsGained}
                    onChange={(e) => setYardsGained(e.target.value)}
                    style={styles.input}
                  />
                </div>
              </div>

              <div style={styles.buttonRow}>
                <button onClick={handleLogPlay} style={styles.buttonPrimary}>
                  Save Play Result
                </button>
              </div>

              {pending && Object.keys(pending).length > 0 ? (
                <div style={styles.reasonBox}>
                  A prediction is currently pending and ready to be logged.
                </div>
              ) : (
                <div style={styles.reasonBox}>
                  No pending play yet. Run a prediction first.
                </div>
              )}
            </div>
          </div>

          {prediction && (
            <div style={{ ...styles.card, marginBottom: "20px" }}>
              <h2
                style={{
                  ...styles.sectionTitle,
                  display: "flex",
                  flexDirection: isMobile ? "column" : "row",
                  alignItems: isMobile ? "flex-start" : "center",
                }}
              >
                Prediction Result
                <span
                  style={{
                    ...styles.badge,
                    background: `${getConfidenceColor(prediction.confidence_tier)}22`,
                    color: getConfidenceColor(prediction.confidence_tier),
                    border: `1px solid ${getConfidenceColor(prediction.confidence_tier)}55`,
                  }}
                >
                  {prediction.confidence_tier}
                </span>
              </h2>

              <div style={styles.predictionBig}>{prediction.prediction}</div>
              <div style={styles.predictionMeta}>
                Confidence: {(prediction.confidence * 100).toFixed(1)}%
                {prediction.tier === 2 ? " • Tier 2" : ""}
              </div>

              <div style={styles.metricRow}>
                <div style={styles.metricBox}>
                  <div style={styles.metricLabel}>Run Probability</div>
                  <div style={styles.metricValue}>
                    {(prediction.run_probability * 100).toFixed(1)}%
                  </div>
                </div>

                <div style={styles.metricBox}>
                  <div style={styles.metricLabel}>Pass Probability</div>
                  <div style={styles.metricValue}>
                    {(prediction.pass_probability * 100).toFixed(1)}%
                  </div>
                </div>
              </div>

              {prediction.play_direction_prediction && (
                <div style={styles.metricRow}>
                  <div style={styles.metricBox}>
                    <div style={styles.metricLabel}>Play Direction</div>
                    <div style={styles.metricValue}>
                      {prediction.play_direction_prediction}
                    </div>
                    {prediction.play_direction_confidence != null && (
                      <div style={styles.predictionMeta}>
                        Confidence: {(prediction.play_direction_confidence * 100).toFixed(1)}%
                      </div>
                    )}
                  </div>

                  <div style={styles.metricBox}>
                    <div style={styles.metricLabel}>Play Concept</div>
                    <div style={styles.metricValue}>
                      {prediction.play_concept_prediction}
                    </div>
                    {prediction.play_concept_confidence != null && (
                      <div style={styles.predictionMeta}>
                        Confidence: {(prediction.play_concept_confidence * 100).toFixed(1)}%
                      </div>
                    )}
                  </div>
                </div>
              )}

              {prediction.defensive_strategy && (
                <>
                  <h3
                    style={{
                      color: "#f8fafc",
                      fontSize: isMobile ? "16px" : "18px",
                      marginBottom: "14px",
                      wordBreak: "break-word",
                    }}
                  >
                    Recommended Defensive Strategy
                  </h3>

                  <div style={styles.strategyGrid}>
                    <div style={styles.strategyItem}>
                      <div style={styles.strategyLabel}>Personnel</div>
                      <div style={styles.strategyValue}>
                        {prediction.defensive_strategy.defensive_personnel}
                      </div>
                    </div>

                    <div style={styles.strategyItem}>
                      <div style={styles.strategyLabel}>Front</div>
                      <div style={styles.strategyValue}>
                        {prediction.defensive_strategy.front}
                      </div>
                    </div>

                    <div style={styles.strategyItem}>
                      <div style={styles.strategyLabel}>Coverage</div>
                      <div style={styles.strategyValue}>
                        {prediction.defensive_strategy.coverage_shell}
                      </div>
                    </div>

                    <div style={styles.strategyItem}>
                      <div style={styles.strategyLabel}>Pressure</div>
                      <div style={styles.strategyValue}>
                        {prediction.defensive_strategy.pressure}
                      </div>
                    </div>

                    <div style={styles.strategyItem}>
                      <div style={styles.strategyLabel}>Aggression</div>
                      <div style={styles.strategyValue}>
                        {prediction.defensive_strategy.aggression}
                      </div>
                    </div>

                    <div style={styles.strategyItem}>
                      <div style={styles.strategyLabel}>Primary Focus</div>
                      <div style={styles.strategyValue}>
                        {prediction.defensive_strategy.primary_focus}
                      </div>
                    </div>
                  </div>

                  <div style={styles.reasonBox}>
                    <strong>Reason:</strong> {prediction.defensive_strategy.reason}
                  </div>
                </>
              )}
            </div>
          )}

          <div style={styles.card}>
            <h2 style={styles.sectionTitle}>Play Log</h2>

            {playLog.length === 0 ? (
              <p style={styles.empty}>No plays logged yet.</p>
            ) : (
              <div style={styles.tableWrap}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>#</th>
                      <th style={styles.th}>Predicted</th>
                      <th style={styles.th}>Actual</th>
                      <th style={styles.th}>Correct</th>
                      <th style={styles.th}>Confidence</th>
                      <th style={styles.th}>Yards</th>
                      <th style={styles.th}>Drive</th>
                    </tr>
                  </thead>
                  <tbody>
                    {playLog.map((play, index) => (
                      <tr key={index}>
                        <td style={styles.td}>{index + 1}</td>
                        <td style={styles.td}>{play.predicted_play_type}</td>
                        <td style={styles.td}>{play.actual_play_type}</td>
                        <td style={styles.td}>
                          {play.correct_prediction ? "Yes" : "No"}
                        </td>
                        <td style={styles.td}>{formatPct(play.confidence)}</td>
                        <td style={styles.td}>{play.yards_gained}</td>
                        <td style={styles.td}>{play.drive_number}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {showSavePrompt && (
          <div style={styles.modalOverlay}>
            <div style={styles.modalCard}>
              <h2 style={styles.sectionTitle}>Save Game</h2>
              <p style={{ ...styles.empty, lineHeight: "1.6" }}>
                Create an account or log in to save your game and view history later.
              </p>
              <div style={styles.buttonRow}>
                <button
                  onClick={() => {
                    setAuthMode("login");
                    setShowSavePrompt(false);
                    setScreen("authChoice");
                  }}
                  style={styles.buttonPrimary}
                >
                  Login
                </button>
                <button
                  onClick={() => {
                    setAuthMode("signup");
                    setShowSavePrompt(false);
                    setScreen("authChoice");
                  }}
                  style={styles.buttonSecondary}
                >
                  Sign Up
                </button>
                <button
                  onClick={() => setShowSavePrompt(false)}
                  style={styles.buttonSecondary}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

export default App;


