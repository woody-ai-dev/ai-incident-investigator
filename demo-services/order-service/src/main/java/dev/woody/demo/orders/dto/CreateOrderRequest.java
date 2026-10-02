package dev.woody.demo.orders.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record CreateOrderRequest(
    @NotBlank
    @Size(max = 64)
    @Pattern(regexp = "[A-Za-z0-9_-]+")
    String productId,

    @NotNull
    @Min(1)
    @Max(100)
    Integer quantity
) {}