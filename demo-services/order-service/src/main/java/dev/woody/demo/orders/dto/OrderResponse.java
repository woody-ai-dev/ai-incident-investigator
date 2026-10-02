package dev.woody.demo.orders.dto;

import java.util.UUID;

public record OrderResponse(UUID orderId, String status) {}
