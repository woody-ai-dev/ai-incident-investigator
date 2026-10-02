package dev.woody.demo.orders.service;

import java.util.UUID;

import org.springframework.stereotype.Component;

import dev.woody.demo.orders.configuration.properties.DemoProperties;
import dev.woody.demo.orders.exception.PaymentTimeoutException;
import lombok.AllArgsConstructor;

@Component
@AllArgsConstructor 
public class SimulatedPaymentGateway implements PaymentGateway {

    private final DemoProperties demoProperties;

    @Override
    public void authorize(UUID orderId) {
        if (demoProperties.paymentMode().isPaymentTimeout()) {
            throw new PaymentTimeoutException(orderId);
        }
    }
}