package 'SysmlRenderPhase0' {
    port def PowerPort;

    part def Battery {
        attribute capacity;
        port powerOut : PowerPort;
    }

    part def Controller {
        port powerIn : ~PowerPort;
    }

    part def ElectricalSystem {
        part battery : Battery;
        part controller : Controller;
        connect battery.powerOut to controller.powerIn;
    }

    part def Vehicle {
        part electrical : ElectricalSystem;
    }

    requirement def MaintainabilityRequirement {
        doc /* The electrical subsystem shall remain independently inspectable. */
    }

    package VehicleArchitecture {
        part vehicle : Vehicle;

        package Requirements {
            requirement maintainability : MaintainabilityRequirement;
        }
    }
}
