import { isOrderStatus, type Order, type Product, type TokenPair } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "Cannot reach the gateway");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  return (await response.json()) as T;
}

async function errorDetail(response: Response): Promise<string> {
  if (response.status === 429) {
    const retryAfter = response.headers.get("Retry-After");
    return retryAfter
      ? `Too many attempts — try again in ${retryAfter}s`
      : "Too many attempts — try again shortly";
  }
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const { detail } = body as { detail: unknown };
      if (typeof detail === "string") return detail;
    }
  } catch {
    // Non-JSON error body (e.g. an HTML page from a proxy).
  }
  return response.statusText || `Request failed (${response.status})`;
}

function authorized(token: string): RequestInit {
  return { headers: { Authorization: `Bearer ${token}` } };
}

export function login(email: string, password: string): Promise<TokenPair> {
  // OAuth2 password flow: form-encoded, and the email goes in `username`.
  return request<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
}

export function refreshTokens(refreshToken: string): Promise<TokenPair> {
  return request<TokenPair>("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

interface OrderDto {
  id: string;
  user_id: string;
  status: string;
  total_amount: string;
  created_at: string;
  updated_at: string;
  items: unknown[];
}

interface ProductDto {
  id: string;
  name: string;
  price: string;
  stock_qty: number;
}

export async function fetchRecentOrders(token: string, limit = 100): Promise<Order[]> {
  const body = await request<{ items: OrderDto[] }>(
    `/api/v1/orders?limit=${limit}`,
    authorized(token),
  );
  return body.items.filter((dto) => isOrderStatus(dto.status)).map(toOrder);
}

export async function fetchProducts(token: string): Promise<Product[]> {
  const body = await request<{ items: ProductDto[] }>(
    "/api/v1/products",
    authorized(token),
  );
  return body.items.map((dto) => ({
    id: dto.id,
    name: dto.name,
    price: Number(dto.price),
    stockQty: dto.stock_qty,
  }));
}

function toOrder(dto: OrderDto): Order {
  return {
    id: dto.id,
    userId: dto.user_id,
    status: dto.status as Order["status"],
    // Decimal arrives as a string; dashboard totals tolerate float rounding.
    totalAmount: Number(dto.total_amount),
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    itemCount: dto.items.length,
  };
}
