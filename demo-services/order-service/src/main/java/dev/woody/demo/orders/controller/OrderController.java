package dev.woody.demo.orders.controller;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import dev.woody.demo.orders.dto.CreateOrderRequest;
import dev.woody.demo.orders.dto.OrderResponse;
import dev.woody.demo.orders.service.OrderService;
import jakarta.validation.Valid;
import lombok.AllArgsConstructor;

@RestController 
@RequestMapping("/api/v1/orders")
@AllArgsConstructor 
public class OrderController {
    
    private final OrderService orderService;

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public OrderResponse createOrder(@Valid @RequestBody CreateOrderRequest request) {
        var orderId = orderService.createOrder(request.productId(), request.quantity());

        return new OrderResponse(orderId, "ACCEPTED");
    } 
}